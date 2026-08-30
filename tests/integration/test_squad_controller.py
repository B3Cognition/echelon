"""Integration tests for SquadController with mock provider.

The most important test: test_consensus_cannot_be_skipped.
A mock agent always returns DONE. SquadController must still dispatch
WHY3 + ASSESS2 (stage 1) before PLAN2 (stage 2) and before checkpoint-plan.
"""
from collections.abc import Mapping
import sys
import json
import hashlib
import re
import copy
import shlex
import shutil
import subprocess
import uuid
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.controller_state_contracts import ControllerStateContractViolation
import harness.squad as squad_module
import harness.squad_completion as completion_module
import harness.git_first_restore as git_first_restore_module
import harness.proportional_quality as proportional_quality_module
import harness.proportional_quality_effects as quality_effects_module
from harness.human_input import (
    HumanInputPolicyError,
    HumanInputPolicy,
    HumanInputOption,
    HumanInputPolicyRegistry,
    HumanInputResolution,
)
from harness.blocked_decision import build_blocked_decision_v2
from harness.phase_graph import PhaseGraph, PhaseNode
from harness.phase_checkpoints import PhaseCheckpointError, load_checkpoint_ledger
from harness.phase_a_readiness import REQUIRED_PHASE_A_BUILD_INPUTS
from harness.prepared_phase_result import prepare_phase_result
from harness.recovery_instruction import (
    RecoveryInstruction,
    RecoveryKind,
    retry_phase_recovery,
)
from harness.squad import (
    ControllerEnrichment,
    SquadController,
    SquadResult,
    _constitution_artifact_is_real,
    _phase_requires_constitution_provenance,
    project_authoring_verdict,
)
from harness.squad_executors import AgentExecutor
from harness.squad_provider import SquadAgentResult
from harness.squad_publication import (
    PreparedSquadPublication,
    PublicationError,
    SquadPublicationTransaction,
)
from harness.squad_completion import (
    CompletionError,
    load_prepared_controller_completion,
    persist_completion_effect_receipt,
    prepare_controller_completion,
)
from harness.squad_state import (
    AdvanceReceipt,
    StateAdvanceError,
    StateDurabilityError,
    SquadStateStore,
)
from harness.state_transaction_namespace import (
    PENDING_CONTROLLER_COMPLETION_KEY,
    PENDING_EXTERNAL_PUBLICATION_KEY,
)
from harness.understanding_gate import UnderstandingGateResult
from echelon.telemetry.phase_timing import record_phase_start
from echelon.telemetry.spec_adapter import analyze_spec_run

DEFINITION = EXT_ROOT / "runtime/workflow/definition.yaml"
PROSAIC_SUBAGENTS = EXT_ROOT / "prosaic/subagents"
PROPORTIONAL_HELLO_WORLD_FIXTURE = (
    EXT_ROOT
    / "tests/fixtures/understanding/proportional-hello-world-first-candidate.md"
)


_RAW_ATTESTATION_SECRET = "raw-attestation-secret"


@pytest.mark.parametrize(
    ("phase", "verdict", "expected"),
    [
        ("phase2-decide", "PASS", {"feasibility_verdict": "PASS"}),
        ("phase2-decide", "KILL", {"feasibility_verdict": "KILL"}),
        ("phase2-decide", "DEFER", {"feasibility_verdict": "DEFER"}),
        (
            "phase2-tracker-alignment",
            "DRIFTING",
            {"intent_alignment_verdict": "DRIFTING"},
        ),
        (
            "phase2-tracker-alignment",
            "ESCALATE",
            {"intent_alignment_verdict": "ESCALATE"},
        ),
    ],
)
def test_project_authoring_verdict(
    phase: str, verdict: str, expected: dict[str, str]
) -> None:
    assert dict(
        project_authoring_verdict(
            phase_id=phase,
            provider_verdict=verdict,
        )
    ) == expected


@pytest.mark.parametrize(
    ("phase", "verdict"),
    [
        ("phase2-decide", "pass"),
        ("phase2-decide", " PASS "),
        ("phase2-decide", ""),
        ("phase2-decide", "ALIGNED"),
        ("phase2-tracker-alignment", "PASS"),
        ("unknown", "PASS"),
    ],
)
def test_project_authoring_verdict_rejects_noncanonical_input(
    phase: str, verdict: str
) -> None:
    with pytest.raises(ControllerStateContractViolation) as caught:
        project_authoring_verdict(
            phase_id=phase,
            provider_verdict=verdict,
        )

    assert caught.value.json_path == "$.verdict"
    assert caught.value.validator == "projection"


def test_only_finalizing_replacement_run_owns_retarget_completion_effect() -> None:
    assert SquadController._active_retarget(
        {
            "run_id": "squad-replacement",
            "retarget": {
                "status": "finalizing",
                "replacement_run_id": "squad-replacement",
            },
        }
    )
    assert not SquadController._active_retarget(
        {
            "run_id": "squad-replacement",
            "retarget": {
                "status": "rebuilding",
                "replacement_run_id": "squad-replacement",
            },
        }
    )


@pytest.mark.parametrize(
    "effect_error",
    ["retarget", "os", "json"],
)
def test_retarget_finalization_error_is_persisted_as_bounded_completion_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    effect_error: str,
) -> None:
    import echelon.spec_retarget_finalization as finalization

    ctrl, store = _controller(tmp_path)
    store.initialize("r", "greenfield", "msg", 0, "phase1-what")
    prepared = prepare_controller_completion(
        tmp_path,
        ctrl._squad_dir,
        completion_id="e" * 32,
        origin="routed",
        publication={"kind": "none"},
        route={
            "kind": "routed",
            "from_phase": "phase1-what",
            "to_phase": "phase1-why1",
            "manual_phase_run": False,
            "record_completion": True,
        },
        effect_plan=("retarget",),
        checkpoint_prestate={"kind": "none"},
        context_reason="retarget failure boundary",
        mine_phase_a=False,
        judgment_payload_sha256=(),
        judgments=(),
    )
    _install_prepared_routed_completion(store, prepared)
    failure = {
        "retarget": finalization.RetargetFinalizationError(
            "retarget finalization receipt drifted"
        ),
        "os": OSError("retarget report read failed"),
        "json": json.JSONDecodeError(
            "retarget manifest parse failed", "{", 0
        ),
    }[effect_error]
    monkeypatch.setattr(
        finalization,
        "apply_or_verify_retarget_finalization",
        MagicMock(side_effect=failure),
    )

    outcome = ctrl._drain_pending_controller_completion()

    failed = store.load()
    assert outcome.recovered is False
    assert failed[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == "retarget"
    assert failed["controller_completion_failure"]["code"] == "receipts_mismatch"


def test_late_retarget_report_drift_keeps_durable_receipt_for_adoption_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live postimage failure after effects are durable is retryable, not fatal."""
    import echelon.spec_retarget_finalization as finalization

    ctrl, store = _controller(tmp_path)
    store.initialize("r", "greenfield", "msg", 0, "phase1-what")
    prepared = prepare_controller_completion(
        tmp_path,
        ctrl._squad_dir,
        completion_id="e" * 32,
        origin="routed",
        publication={"kind": "none"},
        route={
            "kind": "routed",
            "from_phase": "phase1-what",
            "to_phase": "phase1-why1",
            "manual_phase_run": False,
            "record_completion": True,
        },
        effect_plan=("retarget",),
        checkpoint_prestate={"kind": "none"},
        context_reason="late retarget report drift",
        mine_phase_a=False,
        judgment_payload_sha256=(),
        judgments=(),
    )
    _install_prepared_routed_completion(store, prepared)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    state = store.load()
    state.update(
        spec_id="001-demo",
        published_spec_dir="specs/001-demo",
        retarget={
            "status": "finalizing",
            "revision_id": "retarget-1",
            "checkpoint_commit": "a" * 40,
            "replacement_targets": ["apps/web"],
            "replacement_run_id": "replacement",
            "baseline_run_id": "baseline",
            "memory_excluded": True,
            "graph_invalidation": {
                "spec_id": "001-demo",
                "spec_status": "invalidated",
                "spec_graph_hash": None,
                "workspace_status": "not_applicable_empty_workspace",
                "workspace_graph_hash": None,
                "workspace_finding_codes": [],
            },
        },
    )
    store.save(state)
    drawer_ids = ["drawer-1"]
    mine = {
        "schema_version": 1,
        "spec_id": "001-demo",
        "spec_dir": "specs/001-demo",
        "wing": "test",
        "palace_path": "test",
        "status": "complete",
        "expected_count": 1,
        "written_count": 1,
        "adopted_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "drifted_count": 0,
        "unavailable_count": 0,
        "drawer_ids": drawer_ids,
        "expected_drawer_ids": drawer_ids,
        "errors": [],
    }
    for name, contents in {
        "mempalace-audit.json": b'{"status":"pass"}\n',
        "mempalace-audit.md": b"# audit\n",
        "mempalace-mine.json": json.dumps(mine).encode(),
    }.items():
        (spec_dir / name).write_bytes(contents)
    report_digest = finalization._current_memory_report_set_digest(spec_dir)
    (spec_dir / "mempalace-refresh-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "spec_id": "001-demo",
                "files": finalization._current_memory_report_records(spec_dir),
                "report_set_digest": report_digest,
            }
        ),
        encoding="utf-8",
    )
    drawer_digest = "sha256:" + hashlib.sha256(
        json.dumps(drawer_ids, separators=(",", ":")).encode()
    ).hexdigest()
    receipt = {
        "revision_id": "retarget-1",
        "completion_id": "e" * 32,
        "checkpoint_commit": "a" * 40,
        "replacement_targets": ["apps/web"],
        "memory": {
            "status": "pass",
            "spec_id": "001-demo",
            "deleted_count": 0,
            "deleted_ids": [],
            "drawer_set_digest": drawer_digest,
            "mine_status": "complete",
            "audit_status": "pass",
            "adapter": "test",
            "wing": "test",
            "palace_path": "test",
            "scanned_count": 0,
            "delete_acknowledged_count": None,
            "remaining_owned_ids": [],
            "unrelated_missing_ids": [],
            "unrelated_changed_ids": [],
            "unexpected_added_ids": [],
            "report_set_digest": report_digest,
            "failure_code": None,
        },
        "graph": {
            "spec_id": "001-demo",
            "spec_status": "pass",
            "spec_graph_hash": "sha256:" + "b" * 64,
            "workspace_status": "pass",
            "workspace_graph_hash": "sha256:" + "c" * 64,
            "workspace_finding_codes": [],
        },
        "replacement_commit": "d" * 40,
        "status": "complete",
    }
    persist_completion_effect_receipt(prepared, "retarget", receipt)
    one_ahead = load_prepared_controller_completion(
        tmp_path, ctrl._squad_dir, store.load()[PENDING_CONTROLLER_COMPLETION_KEY]
    )
    store.advance_controller_completion(one_ahead)
    monkeypatch.setattr(
        finalization,
        "_configured_mempalace_wing", lambda *_args: "test"
    )
    monkeypatch.setattr(
        finalization,
        "audit_spec_memory",
        lambda *_args, **_kwargs: SimpleNamespace(
            spec_id="001-demo",
            status="pass",
            wing="test",
            palace_path="test",
            expected_count=1,
            present_current_count=1,
            missing=[], stale=[], wrong_wing=[], wrong_room=[], duplicate=[],
            non_canonical=[], lifecycle_excluded=[], errors=[],
        ),
    )
    (spec_dir / "mempalace-audit.md").unlink()
    monkeypatch.setattr(ctrl, "_emit_pending_retarget_comparison", lambda: pytest.fail("emitted comparison"))

    outcome = ctrl._drain_pending_controller_completion()

    failed = store.load()
    assert outcome.recovered is False
    assert failed[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == "complete"
    assert failed["controller_completion_failure"]["code"] == "receipts_mismatch"
    assert failed["retarget"]["status"] == "finalizing"
    assert failed["retarget"]["memory_excluded"] is True
    durable = load_prepared_controller_completion(
        tmp_path, ctrl._squad_dir, failed[PENDING_CONTROLLER_COMPLETION_KEY]
    )
    assert durable.receipts["effects"]["retarget"] == receipt

    (spec_dir / "mempalace-audit.md").write_bytes(b"# audit\n")
    monkeypatch.setattr(
        finalization, "verify_retarget_finalization_receipt", lambda *_args: receipt
    )
    monkeypatch.setattr(
        ctrl, "_apply_controller_completion_effect", lambda *_args: pytest.fail("reran effect")
    )
    monkeypatch.setattr(ctrl, "_emit_pending_retarget_comparison", lambda: True)

    retried = ctrl._drain_pending_controller_completion()

    adopted = store.load()
    assert retried.recovered is True
    assert PENDING_CONTROLLER_COMPLETION_KEY not in adopted
    assert adopted["retarget"]["status"] == "complete"
    assert adopted["retarget"]["finalization_receipt"] == receipt
    assert "memory_excluded" not in adopted["retarget"]


def test_phase4_retarget_enters_finalizing_before_staging(tmp_path: Path) -> None:
    from echelon.spec_retarget_history import (
        RetargetRecoveryProjection,
        advance_retarget_revision,
        append_prepared_revision,
        load_retarget_history,
    )

    ctrl, store = _controller(tmp_path)
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    revision = append_prepared_revision(
        spec_dir,
        operation_id="retarget-operation",
        baseline_run_id="squad-base",
        replacement_run_id="squad-replacement",
        old_targets=("services/api",),
        replacement_targets=("apps/web",),
        original_prompt_digest="sha256:" + "a" * 64,
        recovery=RetargetRecoveryProjection(
            run_id="squad-base",
            status="done",
            phase="phase4-document",
            spec_status="planned",
            completed_phases=(),
            implementation_targets=("services/api",),
            ready_to_build=True,
        ),
    )
    advance_retarget_revision(
        spec_dir,
        revision.revision_id,
        expected_status="prepared",
        status="invalidating",
        updates={},
    )
    advance_retarget_revision(
        spec_dir,
        revision.revision_id,
        expected_status="invalidating",
        status="rebuilding",
        updates={},
    )
    state = store.load()
    state.update(
        {
            "run_id": "squad-replacement",
            "spec_id": "001-demo",
            "retarget": {
                "revision_id": revision.revision_id,
                "status": "rebuilding",
                "replacement_run_id": "squad-replacement",
            },
        }
    )
    store.save(state)

    updated = ctrl._enter_retarget_finalizing(store.load())

    assert updated["retarget"]["status"] == "finalizing"
    assert load_retarget_history(spec_dir).revisions[-1].status == "finalizing"
    assert not SquadController._active_retarget(
        {
            "run_id": "squad-baseline",
            "retarget": {
                "status": "finalizing",
                "replacement_run_id": "squad-replacement",
            },
        }
    )


def test_phase4_staging_never_mutates_a_captured_routing_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller, not staging, must persist finalizing before its snapshot."""
    ctrl, store = _controller(tmp_path)
    state = store.load()
    state.update(
        {
            "phase": "phase4-document",
            "run_id": "squad-replacement",
            "retarget": {
                "status": "rebuilding",
                "replacement_run_id": "squad-replacement",
            },
        }
    )
    store.save(state)
    snapshot = store.capture_routing_snapshot(expected_phase="phase4-document")
    result = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": "DONE", "state_updates": {}},
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    monkeypatch.setattr(
        SquadPublicationTransaction,
        "begin",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("staging reached")),
    )

    with pytest.raises(RuntimeError, match="staging reached"):
        ctrl._prepare_external_phase_effects(
            result,
            "phase4-document",
            snapshot.state,
            manual_phase_run=False,
        )

    assert store.load()["state_revision"] == snapshot.state_revision


def test_completed_retarget_exposes_one_authoritative_comparison_command() -> None:
    assert SquadController._retarget_comparison_command(
        {
            "spec_id": "001-demo",
            "retarget": {
                "status": "complete",
                "checkpoint_commit": "a" * 40,
                "replacement_commit": "b" * 40,
            },
        }
    ) == (
        "Compare old and replacement artifacts:\n"
        "  git diff " + "a" * 40 + ".." + "b" * 40 + " -- specs/001-demo"
    )


def test_pending_retarget_comparison_is_durably_consumed_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl, store = _controller(tmp_path)
    state = store.load()
    state.update(
        {
            "spec_id": "001-demo",
            "retarget": {
                "status": "complete",
                "checkpoint_commit": "a" * 40,
                "replacement_commit": "b" * 40,
                "comparison_pending_completion_id": "c" * 32,
                "finalization_receipt": {"completion_id": "c" * 32},
                "comparison_event_id": "retarget-comparison-" + "c" * 32,
                "comparison_command": (
                    "Compare old and replacement artifacts:\n"
                    "  git diff " + "a" * 40 + ".." + "b" * 40 + " -- specs/001-demo"
                ),
            },
        }
    )
    store.save(state)
    output = MagicMock()
    monkeypatch.setattr("builtins.print", output)

    assert ctrl._emit_pending_retarget_comparison()
    assert not ctrl._emit_pending_retarget_comparison()
    assert output.call_count == 1
    retarget = store.load()["retarget"]
    assert "comparison_pending_completion_id" not in retarget
    assert retarget["comparison_emitted_completion_id"] == "c" * 32


def test_pending_retarget_comparison_rejects_a_receipt_binding_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl, store = _controller(tmp_path)
    state = store.load()
    state.update(
        {
            "spec_id": "001-demo",
            "retarget": {
                "status": "complete",
                "checkpoint_commit": "a" * 40,
                "replacement_commit": "b" * 40,
                "comparison_pending_completion_id": "c" * 32,
                "finalization_receipt": {"completion_id": "d" * 32},
            },
        }
    )
    store.save(state)
    output = MagicMock()
    monkeypatch.setattr("builtins.print", output)

    assert not ctrl._emit_pending_retarget_comparison()
    assert output.call_count == 0
    assert store.load()["retarget"]["comparison_pending_completion_id"] == "c" * 32


def test_deterministic_structural_executor_repairs_without_provider(
    tmp_path: Path,
) -> None:
    ctrl, store = _controller(tmp_path)
    node = ctrl._graph.get("phase2-feasibility-structural")
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    (spec_dir / "feasibility.md").write_text("# Incomplete\n", encoding="utf-8")
    state = store.load()
    state.update(
        {
            "phase": node.id,
            "spec_dir": str(spec_dir),
            "feasibility_verdict": "PASS",
            "iteration": 0,
            "max_iterations": 5,
        }
    )
    store.save(state)

    result = ctrl._executors["deterministic_structural"].execute(node, store)

    assert result.verdict == "REPAIR"
    assert result.state_updates["structural_action"] == "repair"
    assert _evaluate_prepared_result(ctrl, node, result) == "phase2-decide"


def test_deterministic_structural_executor_passes_to_projected_route(
    tmp_path: Path,
) -> None:
    ctrl, store = _controller(tmp_path)
    node = ctrl._graph.get("phase2-feasibility-structural")
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    (spec_dir / "feasibility.md").write_text(
        "# Feasibility\n\n"
        "## Metadata\nSpec: demo\n\n"
        "## Feasibility Verdict\nFeasible.\n\n"
        "## Key Risks\nNo blocking risks.\n\n"
        "## Kill / Defer / Pass Decision\nDecision: PASS\n",
        encoding="utf-8",
    )
    state = store.load()
    state.update(
        {
            "phase": node.id,
            "spec_dir": str(spec_dir),
            "feasibility_verdict": "PASS",
            "iteration": 0,
            "max_iterations": 5,
        }
    )
    store.save(state)

    result = ctrl._executors["deterministic_structural"].execute(node, store)

    assert result.verdict == "PASS"
    assert result.state_updates["structural_action"] == "proceed"
    assert (
        _evaluate_prepared_result(ctrl, node, result)
        == "phase2-strategic-overview"
    )


def test_deterministic_structural_missing_authoring_verdict_blocks(
    tmp_path: Path,
) -> None:
    ctrl, store = _controller(tmp_path)
    node = ctrl._graph.get("phase2-feasibility-structural")
    state = store.load()
    state["phase"] = node.id
    store.save(state)

    result = ctrl._executors["deterministic_structural"].execute(node, store)
    snapshot = store.capture_routing_snapshot(expected_phase=node.id)
    prepared = ctrl._prepare_phase_result(node, result, snapshot)

    assert result.verdict == "FAIL"
    assert prepared.state_updates["structural_action"] == "block"
    assert prepared.control_updates["blocked_reason"] == (
        "governance_structural_authoring_verdict_missing"
    )
    assert (
        ctrl._evaluate_transitions(node, prepared, snapshot)
        == "terminal-blocked"
    )


class _ExplodingPath:
    def __deepcopy__(self, _memo):
        return self

    def __fspath__(self):
        raise RuntimeError(_RAW_ATTESTATION_SECRET)


class _ExplodingMapping(Mapping):
    def __deepcopy__(self, _memo):
        return self

    def __getitem__(self, _key):
        raise KeyError

    def __iter__(self):
        raise RuntimeError(_RAW_ATTESTATION_SECRET)

    def __len__(self):
        return 1


class _ExplodingRepr:
    __slots__ = ()

    def __deepcopy__(self, _memo):
        return self

    def __repr__(self):
        raise RuntimeError(_RAW_ATTESTATION_SECRET)


def _mock_provider(verdict: str = "DONE") -> MagicMock:
    provider = MagicMock()
    default_result = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": verdict,
            "state_updates": {
                "evidence_resolution_status": "not_required",
                "finding_routes": {"findings": []},
            },
        },
        raw_output="",
        duration_ms=100,
        timed_out=False,
    )
    provider.exec_agent.return_value = default_result

    def default_exec_agent(*args, **kwargs):
        configured = provider.exec_agent.return_value
        if configured is not default_result:
            return configured
        result = copy.deepcopy(default_result)
        contract = kwargs.get("result_contract")
        allowed_verdicts = getattr(contract, "allowed_verdicts", frozenset())
        if (
            allowed_verdicts
            and "DONE" not in allowed_verdicts
            and "PASS" in allowed_verdicts
        ):
            result.echelon_result["verdict"] = "PASS"
        allowed = getattr(contract, "allowed_state_update_keys", frozenset())
        required = getattr(contract, "required_state_update_keys", frozenset())
        if allowed or required:
            updates = result.echelon_result["state_updates"]
            retained = {
                key: value
                for key, value in updates.items()
                if key in set(allowed) | set(required)
            }
            if "evidence_resolution_status" in required:
                retained.setdefault(
                    "evidence_resolution_status",
                    "not_required",
                )
            if "finding_routes" in required:
                retained.setdefault("finding_routes", {"findings": []})
            result.echelon_result["state_updates"] = retained
        if "quality_scores" in set(allowed) | set(required):
            result.echelon_result["state_updates"]["quality_scores"] = [{
                "pass": True,
                "pass_id": "WHY2-iter-0",
                "overall": 0.95,
                "structure": 0.95,
                "readability": 0.95,
                "cognitive": 0.95,
                "semantic": 0.95,
                "testability": 0.95,
                "behavioral": 0.95,
                "depth": 0.95,
            }]
        return result

    provider.exec_agent.side_effect = default_exec_agent
    return provider


def _why2_pass_result() -> SquadAgentResult:
    return SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "PASS",
            "state_updates": {
                "evidence_resolution_status": "not_required",
                "finding_routes": {"findings": []},
            },
        },
        raw_output="",
        duration_ms=100,
        timed_out=False,
    )


def _mock_quality_first_flow_provider() -> MagicMock:
    """Return deterministic valid verdicts for the post-Understanding flow."""
    provider = _mock_provider()
    default_exec_agent = provider.exec_agent.side_effect

    def phase_aware_exec_agent(*args, **kwargs):
        prompt = str(args[1])
        if "# Phase: phase1-tracker" in prompt:
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "ALIGNED",
                    "state_updates": {},
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )
        if "# COMMANDER DECISION RESOLUTION" in prompt:
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DECISION_RESOLVED",
                    "state_updates": {},
                    "journal_entries": [],
                    "decision": {
                        "selected_option_id": "approve",
                        "answer_text": None,
                        "rationale": "Approve the compiled workflow checkpoint.",
                        "confidence": "high",
                    },
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )
        if "# Phase: phase1-why2" in prompt:
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "PASS",
                    "state_updates": {
                        "evidence_resolution_status": "not_required",
                        "finding_routes": {"findings": []},
                    },
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )
        if "# Phase: phase2-decide" in prompt:
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "KILL",
                    "state_updates": {},
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )
        return default_exec_agent(*args, **kwargs)

    provider.exec_agent.side_effect = phase_aware_exec_agent
    return provider


def _merge_test_config(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_test_config(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _materialize_canonical_test_config(project_root: Path) -> None:
    config_path = project_root / ".echelon" / "config.yml"
    defaults = yaml.safe_load(
        (EXT_ROOT / "runtime" / "config-template.yml").read_text(encoding="utf-8")
    ) or {}
    overrides = (
        yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if config_path.is_file()
        else {}
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(
            _merge_test_config(defaults, overrides),
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _controller(tmp_path: Path, provider=None, mode: str = "banzai", squad_dir: Path = None):
    if not (tmp_path / ".git").exists():
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Echelon Tests"],
            cwd=tmp_path,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "echelon@example.test"],
            cwd=tmp_path,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "initial"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
    if squad_dir is None:
        squad_dir = tmp_path / "squad" / "run-test"
        squad_dir.mkdir(parents=True, exist_ok=True)
        (squad_dir / "staging").mkdir(exist_ok=True)
    _materialize_canonical_test_config(tmp_path)
    graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
    store = SquadStateStore(squad_dir)
    if provider is None:
        provider = _mock_provider()
    ctrl = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=graph,
        ext_dir=EXT_ROOT / "runtime",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=squad_dir,
    )
    return ctrl, store


def test_prepared_run_preserves_bootstrap_contract_during_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.save(
        {
            "run_id": "prepared-run",
            "status": "preparing",
            "user_message": "Build carefully",
            "spec_authoring_mode": "perfectionist",
            "checkpoint_policy_version": 2,
            "phase_completion_outcomes": [],
        }
    )
    monkeypatch.setattr(ctrl._graph, "entry_phase", lambda: "terminal-blocked")

    ctrl.run("Build carefully", "banzai")

    observed = store.load()
    assert observed["spec_authoring_mode"] == "perfectionist"
    assert observed["checkpoint_policy_version"] == 2
    assert observed["phase_completion_outcomes"] == []


def _install_test_clarification_policy(
    ctrl: SquadController,
    *,
    source_kind: str,
    producer_id: str,
    phase_id: str,
    classification: str = "material",
    reason_code: str = "human_clarification_required",
) -> HumanInputPolicy:
    policy = HumanInputPolicy(
        source_kind=source_kind,
        producer_id=producer_id,
        reason_code=reason_code,
        classification=classification,
        semi_policy="require_human",
        resolution_handler="clarification_resume",
        allow_free_text=True,
        allowed_phase_ids=frozenset({phase_id}),
        allowed_target_phases=frozenset(),
        context_state_keys=("phase",),
        context_paths=(),
        options=(),
    )
    registered_policy = (
        replace(policy, source_kind="provider_escalation")
        if source_kind == "legacy_recovery"
        else policy
    )
    ctrl._human_input_registry = HumanInputPolicyRegistry(
        (registered_policy,)
    )
    return policy


def _mark_constitution_complete(tmp_path: Path, store: SquadStateStore) -> None:
    const_path = tmp_path / ".echelon" / "constitution.md"
    const_path.parent.mkdir(parents=True, exist_ok=True)
    const_path.write_text("# Constitution\n\nReal project rules.\n", encoding="utf-8")
    state = store.load()
    completed = state.get("completed_phases")
    completed_phases = completed if isinstance(completed, list) else []
    if "phase1-constitution" not in completed_phases:
        completed_phases.append("phase1-constitution")
    state["completed_phases"] = completed_phases
    store.save(state)


def _disable_lexicon_gate(tmp_path: Path) -> None:
    """Keep non-Lexicon controller tests focused on their declared behavior."""
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        config_path.read_text(encoding="utf-8").rstrip()
        if config_path.exists()
        else ""
    )
    prefix = f"{existing}\n" if existing else ""
    config_path.write_text(
        f"{prefix}lexicon_gate:\n  enabled: false\n", encoding="utf-8"
    )


def _disable_governance_gate(tmp_path: Path) -> None:
    """Keep non-governance controller tests focused on their declared behavior."""
    config_path = tmp_path / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        config_path.read_text(encoding="utf-8").rstrip()
        if config_path.exists()
        else ""
    )
    prefix = f"{existing}\n" if existing else ""
    config_path.write_text(
        f"{prefix}governance:\n  enabled: false\n", encoding="utf-8"
    )


def _write_phase_a_build_inputs(
    spec_dir: Path,
    *,
    prefix: str = "",
    include_fr: bool = False,
) -> None:
    for name in REQUIRED_PHASE_A_BUILD_INPUTS:
        body = "\nFR-001\n" if include_fr else ""
        content = (
            '{\n'
            '  "status": "pass",\n'
            '  "findings": [],\n'
            '  "sources": ["spec.md", "requirements-overview.md", "plan.md", "tasks.md"]\n'
            '}\n'
            if name == "plan-conformance.json"
            else f"# {prefix}{name}\n{body}"
        )
        (spec_dir / name).write_text(content, encoding="utf-8")


def _sealed_publication_fixture(
    ctrl: SquadController,
) -> tuple[PreparedSquadPublication, dict[str, Path]]:
    targets = {
        "replace": ctrl._project_root / "owned" / "a-replace.txt",
        "create": ctrl._project_root / "owned" / "b-create.txt",
        "delete": ctrl._project_root / "owned" / "c-delete.txt",
    }
    targets["replace"].parent.mkdir(parents=True, exist_ok=True)
    targets["replace"].write_text("old replace\n", encoding="utf-8")
    targets["delete"].write_text("old delete\n", encoding="utf-8")
    transaction = SquadPublicationTransaction.begin(
        ctrl._project_root,
        ctrl._squad_dir,
        uuid.uuid4().hex,
    )
    staged_replace = transaction.build_path("work/a-replace.txt")
    staged_replace.parent.mkdir(parents=True)
    staged_replace.write_text("new replace\n", encoding="utf-8")
    staged_create = transaction.build_path("work/b-create.txt")
    staged_create.write_text("new create\n", encoding="utf-8")
    owned = {
        path.relative_to(ctrl._project_root)
        for path in targets.values()
    }
    transaction.add_write(
        targets["replace"].relative_to(ctrl._project_root),
        staged_replace,
        owned_paths=owned,
    )
    transaction.add_write(
        targets["create"].relative_to(ctrl._project_root),
        staged_create,
        owned_paths=owned,
    )
    transaction.add_delete(
        targets["delete"].relative_to(ctrl._project_root),
        owned_paths=owned,
    )
    return transaction.seal(), targets


def _install_publication_marker(
    store: SquadStateStore,
    prepared: PreparedSquadPublication,
) -> dict[str, object]:
    marker = prepared.marker.to_dict()
    state = store.load()
    state[PENDING_EXTERNAL_PUBLICATION_KEY] = marker
    store.save(state)
    return marker


def _install_empty_routed_completion(
    ctrl: SquadController,
    store: SquadStateStore,
    *,
    from_phase: str = "phase1-what",
    to_phase: str = "phase1-why1",
    manual_phase_run: bool = False,
):
    completion_id = "c" * 32
    prepared_completion = prepare_controller_completion(
        ctrl._project_root,
        ctrl._squad_dir,
        completion_id=completion_id,
        origin="routed",
        publication={"kind": "none"},
        route={
            "kind": "routed",
            "from_phase": from_phase,
            "to_phase": to_phase,
            "manual_phase_run": manual_phase_run,
            "record_completion": True,
        },
        effect_plan=(),
        checkpoint_prestate={"kind": "none"},
        context_reason=f"phase advance {from_phase} -> {to_phase}",
        mine_phase_a=False,
        judgment_payload_sha256=(),
        judgments=(),
    )
    result = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DONE",
            "state_updates": {},
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    prepared_result = prepare_phase_result(
        PhaseNode(
            id=from_phase,
            type="agent",
            allowed_state_updates=[],
        ),
        result,
        controller_updates={},
    )
    snapshot = store.capture_routing_snapshot(
        expected_phase=from_phase
    )
    decision = store.prepare_routing_decision(
        prepared_result,
        snapshot=snapshot,
        from_phase=from_phase,
        to_phase=to_phase,
        manual_phase_run=manual_phase_run,
        dispatch_id=completion_id,
        transaction_state_updates={
            PENDING_CONTROLLER_COMPLETION_KEY: (
                prepared_completion.marker.to_dict()
            ),
        },
    )
    store.advance(from_phase, to_phase, decision)
    return prepared_completion


def _install_prepared_routed_completion(
    store: SquadStateStore,
    prepared_completion,
    *,
    token_usage_delta: int = 0,
) -> None:
    route = prepared_completion.intent.route
    from_phase = str(route["from_phase"])
    to_phase = str(route["to_phase"])
    result = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DONE",
            "state_updates": {},
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    prepared_result = prepare_phase_result(
        PhaseNode(
            id=from_phase,
            type="agent",
            allowed_state_updates=[],
        ),
        result,
        controller_updates={},
    )
    snapshot = store.capture_routing_snapshot(
        expected_phase=from_phase
    )
    transaction_updates = {
        PENDING_CONTROLLER_COMPLETION_KEY: (
            prepared_completion.marker.to_dict()
        ),
    }
    publication = prepared_completion.intent.publication
    if publication["kind"] == "external":
        transaction_updates[PENDING_EXTERNAL_PUBLICATION_KEY] = (
            publication["marker"]
        )
    decision = store.prepare_routing_decision(
        prepared_result,
        snapshot=snapshot,
        from_phase=from_phase,
        to_phase=to_phase,
        judgment_payloads=[
            judgment["echelon_result"]
            for judgment in prepared_completion.intent.judgments
        ],
        manual_phase_run=bool(route["manual_phase_run"]),
        dispatch_id=prepared_completion.marker.completion_id,
        transaction_state_updates=transaction_updates,
        token_usage_delta=token_usage_delta,
    )
    store.advance(from_phase, to_phase, decision)


def _as_previous_release_v1_completion(
    project_root: Path,
    squad_dir: Path,
    prepared,
):
    """Rewrite one staged intent to the exact pre-quality-effect v1 shape."""
    intent_path = prepared._transaction_root / "intent.json"
    intent = json.loads(intent_path.read_bytes())
    assert intent.pop("quality_effect") == {"kind": "none"}
    content = (
        json.dumps(intent, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    intent_path.write_bytes(content)
    marker = replace(
        prepared.marker,
        intent_sha256=hashlib.sha256(content).hexdigest(),
    )
    return load_prepared_controller_completion(
        project_root,
        squad_dir,
        marker,
    )


def test_public_run_recovers_previous_release_routed_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("r", "greenfield", "msg", 0, "phase1-what")
    prepared = prepare_controller_completion(
        tmp_path,
        ctrl._squad_dir,
        completion_id="d" * 32,
        origin="routed",
        publication={"kind": "none"},
        route={
            "kind": "routed",
            "from_phase": "phase1-what",
            "to_phase": "phase1-why1",
            "manual_phase_run": False,
            "record_completion": True,
        },
        effect_plan=(),
        checkpoint_prestate={"kind": "none"},
        context_reason="previous release routed recovery",
        mine_phase_a=False,
        judgment_payload_sha256=(),
        judgments=(),
    )
    legacy = _as_previous_release_v1_completion(
        tmp_path,
        ctrl._squad_dir,
        prepared,
    )
    _install_prepared_routed_completion(store, legacy)
    del ctrl
    fresh, fresh_store = _controller(tmp_path)
    after_recovery = MagicMock(
        side_effect=lambda *_args, **_kwargs: SquadResult.from_state(
            fresh_store.load()
        )
    )
    monkeypatch.setattr(fresh, "_run_locked", after_recovery)

    fresh.run("recover", "banzai")

    recovered = fresh_store.load()
    assert after_recovery.call_count == 1
    assert PENDING_CONTROLLER_COMPLETION_KEY not in recovered
    assert recovered["last_dispatch"]["post_dispatch_complete"] is True
    assert recovered["last_dispatch"]["completion_intent_sha256"] == (
        legacy.marker.intent_sha256
    )


def test_public_run_recovers_previous_release_terminal_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("r", "greenfield", "msg", 0, "DONE")
    active = ctrl._squad_dir / "specs/001-demo"
    published = tmp_path / "specs/001-demo"
    active.mkdir(parents=True)
    published.mkdir(parents=True)
    content = b"# Previous-release terminal completion\n"
    (active / "spec.md").write_bytes(content)
    (published / "spec.md").write_bytes(content)
    state = store.load()
    state.update(
        {
            "status": "done",
            "spec_id": "001-demo",
            "spec_dir": str(active.relative_to(tmp_path)),
            "published_spec_dir": str(published.relative_to(tmp_path)),
        }
    )
    store.save(state)
    prepared = prepare_controller_completion(
        tmp_path,
        ctrl._squad_dir,
        completion_id="e" * 32,
        origin="terminal",
        publication={"kind": "none"},
        route={"kind": "terminal", "terminal_phase": "DONE"},
        effect_plan=(),
        checkpoint_prestate={"kind": "none"},
        context_reason="previous release terminal recovery",
        mine_phase_a=False,
        judgment_payload_sha256=(),
        judgments=(),
    )
    legacy = _as_previous_release_v1_completion(
        tmp_path,
        ctrl._squad_dir,
        prepared,
    )
    snapshot = store.capture_routing_snapshot(expected_phase="DONE")
    store.begin_terminal_controller_completion(legacy, snapshot=snapshot)
    del ctrl
    fresh, fresh_store = _controller(tmp_path)
    after_recovery = MagicMock(
        side_effect=lambda *_args, **_kwargs: SquadResult.from_state(
            fresh_store.load()
        )
    )
    monkeypatch.setattr(fresh, "_run_locked", after_recovery)

    fresh.run("recover", "banzai")

    recovered = fresh_store.load()
    assert after_recovery.call_count == 1
    assert PENDING_CONTROLLER_COMPLETION_KEY not in recovered
    assert recovered["last_terminal_completion"]["intent_sha256"] == (
        legacy.marker.intent_sha256
    )


def _test_payload_sha256(payload: dict[str, object]) -> str:
    return squad_module._canonical_payload_sha256(payload)


def _install_single_effect_completion(
    tmp_path: Path,
    effect: str,
):
    ctrl, store = _controller(tmp_path)
    completion_id = uuid.uuid4().hex
    if effect == "mining":
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "DONE",
        )
        active = tmp_path / "runs" / "r" / "specs" / "001-demo"
        published = tmp_path / "specs" / "001-demo"
        active.mkdir(parents=True)
        published.mkdir(parents=True)
        spec_bytes = (
            b"# Demo\n\n"
            b"## Requirements\n\n"
            b"- FR-001: The system SHALL recover deterministically.\n"
        )
        (active / "spec.md").write_bytes(spec_bytes)
        (published / "spec.md").write_bytes(spec_bytes)
        state = store.load()
        state.update(
            {
                "phase": "DONE",
                "status": "done",
                "spec_id": "001-demo",
                "spec_dir": str(active.relative_to(tmp_path)),
                "published_spec_dir": str(
                    published.relative_to(tmp_path)
                ),
            }
        )
        store.save(state)
        prepared = prepare_controller_completion(
            tmp_path,
            ctrl._squad_dir,
            completion_id=completion_id,
            origin="terminal",
            publication={"kind": "none"},
            route={
                "kind": "terminal",
                "terminal_phase": "DONE",
            },
            effect_plan=("mining",),
            checkpoint_prestate={"kind": "none"},
            context_reason="terminal restart matrix",
            mine_phase_a=True,
            judgment_payload_sha256=(),
            judgments=(),
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase="DONE"
        )
        store.begin_terminal_controller_completion(
            prepared,
            snapshot=snapshot,
        )
        return ctrl, store, prepared

    from_phase = (
        "phase3-specialists"
        if effect == "timing"
        else "phase1-what"
    )
    to_phase = (
        "phase3-how"
        if effect == "timing"
        else "phase1-why1"
    )
    store.initialize(
        "r",
        "greenfield",
        "msg",
        0,
        from_phase,
    )
    checkpoint_prestate: dict[str, object] = {"kind": "none"}
    if effect == "checkpoint":
        spec_dir = ctrl._squad_dir / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "# Completion checkpoint\n",
            encoding="utf-8",
        )
        state = store.load()
        state["spec_id"] = "001-demo"
        state["spec_dir"] = str(spec_dir.relative_to(tmp_path))
        store.save(state)
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        checkpoint_prestate = {
            "kind": "git_head",
            "head": head,
        }
    if effect == "timing":
        ctrl._ensure_telemetry_manifest()
        budget = ctrl._declared_phase_timing_budget(
            "phase2-decide"
        )
        assert budget is not None
        record_phase_start(
            ctrl._telemetry_store,
            phase="phase2-decide",
            budget_seconds=budget,
        )
    judgments: tuple[dict[str, object], ...] = ()
    judgment_digests: tuple[str, ...] = ()
    if effect == "journal":
        payload = {
            "verdict": "DONE",
            "state_updates": {},
            "journal_entries": [
                {
                    "type": "decision",
                    "agent": "task7",
                    "data": {"boundary": "fresh-controller"},
                }
            ],
        }
        judgments = (
            {
                "echelon_result": payload,
                "quarantined_state_updates": {},
            },
        )
        judgment_digests = (_test_payload_sha256(payload),)
    prepared = prepare_controller_completion(
        tmp_path,
        ctrl._squad_dir,
        completion_id=completion_id,
        origin="routed",
        publication={"kind": "none"},
        route={
            "kind": "routed",
            "from_phase": from_phase,
            "to_phase": to_phase,
            "manual_phase_run": False,
            "record_completion": True,
        },
        effect_plan=(effect,),
        checkpoint_prestate=checkpoint_prestate,
        context_reason=f"{effect} restart matrix",
        mine_phase_a=False,
        judgment_payload_sha256=judgment_digests,
        judgments=judgments,
    )
    _install_prepared_routed_completion(
        store,
        prepared,
        token_usage_delta=17,
    )
    return ctrl, store, prepared


def _configure_tasks_lexicon_route(
    ctrl: SquadController,
    store: SquadStateStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store.initialize(
        "r",
        "greenfield",
        "msg",
        0,
        "phase3-tasks-lexicon",
    )
    executor = MagicMock()
    executor.execute.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DONE",
            "state_updates": {
                "tasks_lexicon_action": "proceed",
                "tasks_lexicon_pass": True,
                "tasks_lexicon_attempts": 0,
                "tasks_lexicon_findings": 0,
                "tasks_lexicon_report": "tasks-lexicon-report.json",
            },
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    ctrl._executors["deterministic_lexicon"] = executor
    monkeypatch.setattr(
        ctrl,
        "_guard_constitution_provenance",
        lambda phase: phase,
    )
    monkeypatch.setattr(
        ctrl,
        "_guard_spec_lexicon_evidence",
        lambda phase: phase,
    )
    monkeypatch.setattr(
        ctrl,
        "_guard_understanding_evidence",
        lambda phase: phase,
    )
    monkeypatch.setattr(ctrl, "_ensure_telemetry_manifest", lambda: None)


def _prepare_checkpoint_boundary(
    ctrl: SquadController,
    store: SquadStateStore,
) -> None:
    snapshot = store.capture_routing_snapshot(
        expected_phase="phase1-what",
    )
    ctrl._prepare_controller_completion(
        from_phase="phase1-what",
        to_phase="phase1-why1",
        snapshot=snapshot,
        manual_phase_run=False,
        conditional_skip=False,
        record_completion=False,
        publication_marker=None,
    )


def _assert_checkpoint_preparation_unchanged(
    ctrl: SquadController,
    store: SquadStateStore,
    *,
    state_bytes: bytes,
    state: dict[str, object],
    artifact_bytes: bytes,
) -> None:
    assert store._path.read_bytes() == state_bytes
    assert store.load() == state
    assert (ctrl._project_root / "artifact.txt").read_bytes() == (
        artifact_bytes
    )
    assert not (ctrl._squad_dir / ".completion-outbox").exists()
    assert not (ctrl._squad_dir / ".publication-outbox").exists()


def _assert_only_token_accounting_changed(
    before: dict[str, object],
    after: dict[str, object],
    *,
    token_delta: int,
    accounting_updates: int = 1,
) -> None:
    assert after["token_usage"] == before["token_usage"] + token_delta
    assert (
        after["state_revision"]
        == before["state_revision"] + accounting_updates
    )
    before_rest = dict(before)
    after_rest = dict(after)
    for key in ("token_usage", "state_revision", "updated_at"):
        before_rest.pop(key, None)
        after_rest.pop(key, None)
    assert after_rest == before_rest


@pytest.mark.parametrize(
    "git_result",
    (
        subprocess.CalledProcessError(128, ["git", "rev-parse"]),
        SimpleNamespace(stdout="not-an-object-id\n"),
        SimpleNamespace(stdout=f"{'0' * 40}\n"),
    ),
    ids=("command-failure", "invalid-object-id", "zero-sentinel"),
)
def test_active_checkpoint_prestate_failure_is_side_effect_free(
    tmp_path: Path,
    git_result: object,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize(
        "r",
        "greenfield",
        "message",
        0,
        "phase1-what",
    )
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("unchanged\n", encoding="utf-8")
    state_bytes = store._path.read_bytes()
    state = store.load()
    artifact_bytes = artifact.read_bytes()

    replacement = (
        patch(
            "harness.squad.subprocess.run",
            side_effect=git_result,
        )
        if isinstance(git_result, BaseException)
        else patch(
            "harness.squad.subprocess.run",
            return_value=git_result,
        )
    )
    with replacement, pytest.raises(StateAdvanceError) as raised:
        _prepare_checkpoint_boundary(ctrl, store)

    assert raised.value.validator == "checkpoint_prestate"
    _assert_checkpoint_preparation_unchanged(
        ctrl,
        store,
        state_bytes=state_bytes,
        state=state,
        artifact_bytes=artifact_bytes,
    )


def test_active_checkpoint_prestate_rejects_unborn_repository(
    tmp_path: Path,
) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    ctrl, store = _controller(tmp_path)
    store.initialize(
        "r",
        "greenfield",
        "message",
        0,
        "phase1-what",
    )
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("unchanged\n", encoding="utf-8")
    state_bytes = store._path.read_bytes()
    state = store.load()
    artifact_bytes = artifact.read_bytes()

    with pytest.raises(StateAdvanceError) as raised:
        _prepare_checkpoint_boundary(ctrl, store)

    assert raised.value.validator == "checkpoint_prestate"
    _assert_checkpoint_preparation_unchanged(
        ctrl,
        store,
        state_bytes=state_bytes,
        state=state,
        artifact_bytes=artifact_bytes,
    )


def test_inactive_checkpoint_does_not_resolve_git_prestate(
    tmp_path: Path,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize(
        "r",
        "greenfield",
        "message",
        0,
        "phase1-what",
    )
    snapshot = store.capture_routing_snapshot(
        expected_phase="phase1-what",
    )

    with patch(
        "harness.squad.subprocess.run",
        side_effect=AssertionError("checkpoint prestate was resolved"),
    ):
        prepared = ctrl._prepare_controller_completion(
            from_phase="phase1-what",
            to_phase="phase1-why1",
            snapshot=snapshot,
            manual_phase_run=False,
            conditional_skip=False,
            record_completion=True,
            publication_marker=None,
        )

    assert "checkpoint" not in prepared.intent.effect_plan
    assert prepared.intent.checkpoint_prestate == {"kind": "none"}


@pytest.mark.parametrize(
    ("phase", "conditional_skip", "checkpoint_expected"),
    [
        ("phase1-discover", False, True),
        ("phase1-discover", True, False),
        ("init", False, False),
    ],
)
def test_versioned_completion_effect_plan_follows_phase_policy(
    tmp_path: Path,
    phase: str,
    conditional_skip: bool,
    checkpoint_expected: bool,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("r", "greenfield", "message", 0, phase)
    spec_dir = ctrl._squad_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    state = store.load()
    state.update({
        "checkpoint_policy_version": 2,
        "phase_completion_outcomes": [],
        "spec_id": "001-demo",
        "spec_dir": str(spec_dir.relative_to(tmp_path)),
    })
    store.save(state)

    prepared = ctrl._prepare_controller_completion(
        from_phase=phase,
        to_phase="phase1-discover",
        snapshot=store.capture_routing_snapshot(expected_phase=phase),
        manual_phase_run=False,
        conditional_skip=conditional_skip,
        record_completion=True,
        publication_marker=None,
    )

    assert ("checkpoint" in prepared.intent.effect_plan) is checkpoint_expected
    assert prepared.intent.route["checkpoint_policy_version"] == 2
    assert prepared.intent.route["checkpoint_policy"] == (
        "required" if phase == "phase1-discover" else "none"
    )


def test_versioned_phase_a_nodes_checkpoint_before_next_dispatch_and_rewind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    from echelon.checkpoint_cli import run_checkpoint_command
    from echelon.cli import _cmd_rewind

    provider = _mock_provider()
    default_dispatch = provider.exec_agent.side_effect
    run_dir = tmp_path / "runs" / "spec-run-1"
    ctrl, store = _controller(tmp_path, provider=provider, squad_dir=run_dir)
    subprocess.run(
        ["git", "branch", "-m", "001-demo"],
        cwd=tmp_path,
        check=True,
    )
    spec_dir = run_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    store.initialize(
        "spec-run-1",
        "greenfield",
        "Build a simple notes application",
        0,
        "phase1-discover",
        autonomy_mode="banzai",
    )
    state = store.load()
    state.update(
        {
            "checkpoint_policy_version": 2,
            "phase_completion_outcomes": [],
            "spec_id": "001-demo",
            "feature_branch": "001-demo",
            "spec_dir": spec_dir.relative_to(tmp_path).as_posix(),
        }
    )
    store.save(state)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    last_executed_completion = ""

    def dispatch_with_artifacts(*args, **kwargs):
        nonlocal last_executed_completion
        prompt = str(args[1])
        match = re.search(r"^# Phase: ([^\n]+)$", prompt, re.MULTILINE)
        assert match is not None
        phase = match.group(1)
        if last_executed_completion:
            assert any(
                row.completion_id == last_executed_completion
                for row in load_checkpoint_ledger(spec_dir).checkpoints
            )
        if phase == "phase1-discover":
            (spec_dir / "glossary.md").write_text("discover\n", encoding="utf-8")
        elif phase == "phase1-synthesizer":
            (spec_dir / "glossary.md").write_text("synthesized\n", encoding="utf-8")
        elif phase == "phase1-tracker":
            (spec_dir / "user-intent.md").write_text("simple notes\n", encoding="utf-8")
        elif phase == "phase1-constitution":
            constitution = tmp_path / ".echelon" / "constitution.md"
            constitution.write_text("# Constitution\n", encoding="utf-8")
        elif phase == "phase1-what":
            (spec_dir / "spec.md").write_text("# Notes\n", encoding="utf-8")
            (spec_dir / "requirements-overview.md").write_text(
                "# Requirements\n",
                encoding="utf-8",
            )
        result = default_dispatch(*args, **kwargs)
        if phase == "phase1-tracker":
            result.echelon_result["verdict"] = "ALIGNED"
        if phase == "phase1-constitution":
            result.echelon_result["state_updates"] = {
                "constitution_status": "exists"
            }
        return result

    provider.exec_agent.side_effect = dispatch_with_artifacts
    executed = [
        "phase1-discover",
        "phase1-synthesizer",
        "phase1-tracker",
        "phase1-why1",
        "phase1-constitution",
        "phase1-what",
    ]
    expected_paths = {
        "phase1-discover": {"runs/spec-run-1/specs/001-demo/glossary.md"},
        "phase1-synthesizer": {"runs/spec-run-1/specs/001-demo/glossary.md"},
        "phase1-tracker": {"runs/spec-run-1/specs/001-demo/user-intent.md"},
        "phase1-why1": set(),
        "phase1-constitution": {".echelon/constitution.md"},
        "phase1-what": {
            "runs/spec-run-1/specs/001-demo/spec.md",
            "runs/spec-run-1/specs/001-demo/requirements-overview.md",
        },
    }

    for phase in executed[:2]:
        node = ctrl._materialize_controller_phase_inputs(ctrl._graph.get(phase))
        parent = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        result = ctrl._executors[node.type].execute(node, store)
        _coordinate_prepared_result(ctrl, node, result)
        row = load_checkpoint_ledger(spec_dir).checkpoints[-1]
        last_executed_completion = row.completion_id
        body = subprocess.run(
            ["git", "show", "-s", "--format=%B", row.commit], cwd=tmp_path,
            check=True, capture_output=True, text=True,
        ).stdout
        assert "Co-authored-by: Echelon <echelon@b3cognition.dev>" in body
        assert f"Echelon-Completion: {row.completion_id}" in body
        assert subprocess.run(
            ["git", "show", "-s", "--format=%P", row.commit], cwd=tmp_path,
            check=True, capture_output=True, text=True,
        ).stdout.strip() == parent
        assert set(subprocess.run(
            ["git", "show", "--format=", "--name-only", row.commit], cwd=tmp_path,
            check=True, capture_output=True, text=True,
        ).stdout.split()) == expected_paths[phase]

    modeler = ctrl._graph.get("phase1-modeler")
    head_before_skip = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    dispatches_before_skip = provider.exec_agent.call_count
    assert ctrl._skip_phase_if_condition_false(modeler, manual_phase_run=False)
    skipped = store.load()["phase_completion_outcomes"][-1]
    assert skipped["phase"] == "phase1-modeler"
    assert skipped["outcome"] == "skipped"
    assert provider.exec_agent.call_count == dispatches_before_skip
    assert subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
        capture_output=True, text=True,
    ).stdout.strip() == head_before_skip
    assert not any(
        row.completion_id == skipped["completion_id"]
        for row in load_checkpoint_ledger(spec_dir).checkpoints
    )

    for phase in executed[2:]:
        node = ctrl._materialize_controller_phase_inputs(ctrl._graph.get(phase))
        parent = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        result = ctrl._executors[node.type].execute(node, store)
        _coordinate_prepared_result(ctrl, node, result)
        row = load_checkpoint_ledger(spec_dir).checkpoints[-1]
        last_executed_completion = row.completion_id
        body = subprocess.run(
            ["git", "show", "-s", "--format=%B", row.commit], cwd=tmp_path,
            check=True, capture_output=True, text=True,
        ).stdout
        assert "Co-authored-by: Echelon <echelon@b3cognition.dev>" in body
        assert f"Echelon-Completion: {row.completion_id}" in body
        assert subprocess.run(
            ["git", "show", "-s", "--format=%P", row.commit], cwd=tmp_path,
            check=True, capture_output=True, text=True,
        ).stdout.strip() == parent
        assert set(subprocess.run(
            ["git", "show", "--format=", "--name-only", row.commit], cwd=tmp_path,
            check=True, capture_output=True, text=True,
        ).stdout.split()) == expected_paths[phase]

    monkeypatch.setattr(
        "harness.phase_graph.load_workspace_phase_graph",
        lambda _root: (ctrl._graph, ctrl._ext_dir),
    )
    run_checkpoint_command(
        ["list", "--strict", "--spec", run_dir.name],
        project_root=tmp_path,
    )
    assert "missing" not in capsys.readouterr().out

    constitution_row = next(
        row
        for row in load_checkpoint_ledger(spec_dir).checkpoints
        if row.phase == "phase1-constitution"
    )
    (spec_dir / "later.md").write_text("later\n", encoding="utf-8")
    subprocess.run(["git", "add", spec_dir / "later.md"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "test: later artifact"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    _cmd_rewind(
        ["phase1-constitution", "--commit", constitution_row.commit[:12], "--confirm"],
        project_root=tmp_path,
    )

    rewound = store.load()
    assert subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True,
        capture_output=True, text=True,
    ).stdout.strip() == constitution_row.commit
    assert not (spec_dir / "spec.md").exists()
    assert not (spec_dir / "later.md").exists()
    assert rewound["phase"] == "phase1-constitution"
    assert all(
        row["completion_id"] != constitution_row.boundary_completion_id
        for row in rewound["phase_completion_outcomes"]
    )


def test_versioned_required_checkpoint_rejects_missing_spec_target(
    tmp_path: Path,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("r", "greenfield", "message", 0, "phase1-discover")
    state = store.load()
    state.update({
        "checkpoint_policy_version": 2,
        "phase_completion_outcomes": [],
    })
    store.save(state)
    before = store.load()

    with pytest.raises(StateAdvanceError) as raised:
        ctrl._prepare_controller_completion(
            from_phase="phase1-discover",
            to_phase="phase1-synthesizer",
            snapshot=store.capture_routing_snapshot(
                expected_phase="phase1-discover"
            ),
            manual_phase_run=False,
            conditional_skip=False,
            record_completion=True,
            publication_marker=None,
        )

    assert raised.value.validator == "checkpoint_target"
    assert "phase_checkpoint_target_missing: phase1-discover" in str(raised.value)
    assert store.load() == before
    assert not (ctrl._squad_dir / ".completion-outbox").exists()


def test_human_input_spec_root_fallback_is_legacy_only(tmp_path: Path) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("r", "greenfield", "message", 0, "phase1-tracker")

    legacy_roots = ctrl._authoritative_human_input_roots(store.load())
    assert legacy_roots["{spec_dir}"] == store.staging_dir

    state = store.load()
    state.update({
        "checkpoint_policy_version": 2,
        "phase_completion_outcomes": [],
    })
    store.save(state)

    versioned_roots = ctrl._authoritative_human_input_roots(store.load())
    assert versioned_roots["{spec_dir}"] is None


def test_routed_checkpoint_prestate_failure_records_only_deferred_tokens(
    tmp_path: Path,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize(
        "r",
        "greenfield",
        "message",
        0,
        "phase1-what",
    )
    spec_dir = ctrl._squad_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
    state = store.load()
    state["spec_id"] = "001-demo"
    state["spec_dir"] = str(spec_dir.relative_to(tmp_path))
    store.save(state)
    node = PhaseNode(
        id="phase1-what",
        type="agent",
        allowed_state_updates=[],
        transitions=[{"condition": "always", "to": "phase1-why1"}],
    )
    result = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": "DONE", "state_updates": {}},
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    prepared = prepare_phase_result(
        node,
        result,
        controller_updates={},
    )
    snapshot = store.capture_routing_snapshot(
        expected_phase=node.id,
    )
    publication, _ = _sealed_publication_fixture(ctrl)
    publication_root = (
        ctrl._squad_dir
        / ".publication-outbox"
        / publication.marker.transaction_id
    )
    before = store.load()
    usage_result = replace(result, token_usage=17)

    def fail_after_usage() -> dict[str, object]:
        ctrl._record_provider_usage(usage_result)
        raise StateAdvanceError(
            "checkpoint unavailable",
            validator="checkpoint_prestate",
        )

    with patch.object(
        ctrl,
        "_completion_checkpoint_prestate",
        side_effect=fail_after_usage,
    ):
        decision = ctrl._construct_routing_decision_or_block(
            node,
            prepared,
            snapshot,
            additional_state_updates={
                PENDING_EXTERNAL_PUBLICATION_KEY: (
                    publication.marker.to_dict()
                ),
            },
        )
    if decision is None:
        ctrl._discard_publication_without_authority(publication)

    assert decision is None
    _assert_only_token_accounting_changed(
        before,
        store.load(),
        token_delta=17,
    )
    assert not publication_root.exists()
    assert not (ctrl._squad_dir / ".completion-outbox").exists()


def _evaluate_prepared_result(
    ctrl: SquadController,
    node: PhaseNode,
    result: SquadAgentResult,
) -> str:
    state = ctrl._state_store.load()
    if not isinstance(state.get("phase"), str) or not state["phase"]:
        state["phase"] = node.id
        ctrl._state_store.save(state)
    snapshot = ctrl._state_store.capture_routing_snapshot()
    prepared = ctrl._prepare_phase_result(node, result, snapshot)
    return ctrl._evaluate_transitions(
        node,
        prepared,
        snapshot,
    )


def _coordinate_prepared_result(
    ctrl: SquadController,
    node: PhaseNode,
    result: SquadAgentResult,
) -> str:
    snapshot = ctrl._state_store.capture_routing_snapshot(
        expected_phase=node.id
    )
    routed_human_input = []
    decision = ctrl._coordinate_transition_routing(
        node,
        ctrl._prepare_phase_result(node, result, snapshot),
        snapshot,
        human_input_collector=routed_human_input,
    )
    if routed_human_input:
        ctrl.handle_human_input(
            routed_human_input[0],
            provider_advance=squad_module._ProviderHumanInputAdvance(
                from_phase=decision.from_phase,
                to_phase=decision.to_phase,
                decision=decision,
            ),
        )
    else:
        assert ctrl._advance_prepared_result_or_block(node, decision) is not None
    return decision.to_phase


def _valid_lexicon_spec() -> str:
    return """ARTIFACT: SPEC
TITLE: Dashboard

REQ: FR-001
GIVEN: data is available
WHEN: the user opens the dashboard
THEN: The system SHALL render the dashboard
OUTPUT: The dashboard is visible
DEPENDS: none
EXAMPLE: AC-001

AC: AC-001
GIVEN: data is available
WHEN: the user opens the dashboard
THEN: The dashboard is visible
"""


def _valid_tasks() -> str:
    return """# Tasks

- [ ] T-001 complexity=standard phase=phase4-build req=FR-001 depends=none target=sources/app
  **Title:** Render dashboard
  **Description:** Render the dashboard from available data.
  **Files:** `sources/app/dashboard.py`
  **Test:** Open the dashboard with seeded data.
  **Acceptance Criteria:**
  - [ ] The dashboard is visible.
"""


def _write_valid_plan_artifacts(spec_dir: Path) -> None:
    (spec_dir / "requirements.lexicon.md").write_text(
        _valid_lexicon_spec(), encoding="utf-8"
    )
    (spec_dir / "tasks.md").write_text(_valid_tasks(), encoding="utf-8")
    for name in ("critical-path.md", "risk-matrix.md", "dependencies.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    (spec_dir / "targets.yml").write_text(
        "schema_version: 1\n"
        "targets:\n"
        "  - id: app\n"
        "    path: sources/app\n"
        "    role: primary\n",
        encoding="utf-8",
    )


def _install_passing_understanding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unrelated routing tests independent of metric-engine thresholds."""

    def run_gate(**kwargs: object) -> UnderstandingGateResult:
        project_root = Path(kwargs["project_root"])
        squad_dir = Path(kwargs["squad_dir"])
        spec_dir = Path(str(kwargs["spec_dir"]))
        if not spec_dir.is_absolute():
            spec_dir = project_root / spec_dir
        spec_path = spec_dir / "spec.md"
        spec_digest = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        phase = str(kwargs["phase"])
        iteration = int(kwargs["iteration"])
        scores = {
            "overall": 0.95,
            "structure": 0.95,
            "testability": 0.95,
            "semantic": 0.95,
            "cognitive": 0.95,
            "readability": 0.95,
            "depth": 0.95,
            "behavioral": 0.95,
        }
        report = {
            "schema_version": 1,
            "status": "completed",
            "phase": phase,
            "iteration": iteration,
            "spec": {"path": str(spec_path), "sha256": spec_digest},
            "thresholds": {key: 0.5 for key in scores},
            "scores": scores,
            "gates": {
                key: {"score": value, "threshold": 0.5, "pass": True}
                for key, value in scores.items()
            },
            "pass": True,
            "requirement_count": 1,
            "per_requirement": [],
            "entity_analysis": {},
            "behavioral_analysis": {},
            "diagrams": {"enabled": False, "status": "skipped", "outputs": []},
            "findings": [],
            "generated_at": "2026-07-22T00:00:00+00:00",
        }
        report_path = (
            squad_dir
            / "evidence"
            / "understanding"
            / f"{phase}-iter-{iteration}.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
        return UnderstandingGateResult(
            completed=True,
            passed=True,
            phase=phase,
            iteration=iteration,
            report_path=report_path,
            report_digest=report_digest,
            report=report,
        )

    monkeypatch.setattr("harness.squad_executors.run_understanding_gate", run_gate)


def _write_re_index_generation(
    root: Path,
    generation: int,
    *,
    published_from_run: str = "fixture",
) -> None:
    path = root / "re" / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation": generation,
                "publication_status": "complete",
                "published_at": "2026-07-12T12:00:00+00:00",
                "published_from_run": published_from_run,
                "sources": {},
                "workspace": {
                    "manifest": "re/workspace/manifest.json",
                    "overview": "re/workspace/overview.md",
                    "relationships": "re/workspace/relationships.md",
                    "contracts": "re/workspace/contracts.md",
                },
                "warnings": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_checkpoint_successful_phase_blocks_when_required_checkpoint_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("spec-run", "greenfield", "msg", 0, "phase3-plan")
    spec_dir = tmp_path / "squad" / "run-test" / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    state = store.load()
    state["spec_id"] = "001-demo"
    state["spec_dir"] = str(spec_dir.relative_to(tmp_path))
    store.save(state)

    def fail_checkpoint(**_kwargs: object) -> None:
        raise PhaseCheckpointError("simulated checkpoint failure")

    monkeypatch.setattr("harness.squad.create_phase_checkpoint", fail_checkpoint)

    assert ctrl._checkpoint_successful_phase("phase3-plan", "phase3-consensus") is False
    state = store.load()
    assert state["status"] == "blocked"
    assert state["phase"] == "terminal-blocked"
    assert state["blocked_reason"] == (
        "phase_checkpoint_failed: phase3-plan: simulated checkpoint failure"
    )


def test_checkpoint_successful_phase_is_non_blocking_without_active_spec(
    tmp_path: Path,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("spec-run", "greenfield", "msg", 0, "phase1-discover")

    assert ctrl._checkpoint_successful_phase("phase1-discover", "phase1-why1") is True
    assert store.load()["status"] == "running"


def test_checkpoint_successful_phase_returns_true_after_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl, store = _controller(tmp_path)
    store.initialize("spec-run", "greenfield", "msg", 0, "phase1-what")
    spec_dir = tmp_path / "squad" / "run-test" / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    state = store.load()
    state["spec_id"] = "001-demo"
    state["spec_dir"] = str(spec_dir.relative_to(tmp_path))
    store.save(state)
    checkpoint_calls: list[dict[str, object]] = []

    def record_checkpoint(**kwargs: object) -> object:
        checkpoint_calls.append(kwargs)
        return object()

    monkeypatch.setattr("harness.squad.create_phase_checkpoint", record_checkpoint)

    assert ctrl._checkpoint_successful_phase("phase1-what", "phase1-why2") is True
    assert checkpoint_calls[0]["spec_dir"] == spec_dir
    assert store.load()["status"] == "running"


def test_cartographer_context_preservation_requires_spec_md(tmp_path: Path) -> None:
    """A reserved run-local path must not suppress the initial WHAT pass."""
    ctrl, store = _controller(tmp_path)
    store.initialize("spec-run", "banzai", "msg", 0, "phase1-what")
    planned = tmp_path / "runs" / "spec-run" / "specs" / "001-demo"
    planned.mkdir(parents=True)
    state = store.load()
    state["spec_id"] = "001-demo"
    state["spec_dir"] = str(planned.relative_to(tmp_path))
    store.save(state)

    state = store.load()
    ctrl._preserve_cartographer_spec_context(state)

    assert "cartographer_resume_existing_spec" not in state


class TestConsensusCannotBeSkipped:
    """Regression: phase3-consensus was previously skipped via EVOI fabrication.
    The plan now routes through deterministic Tasks Lexicon and Understanding
    nodes before consensus. Python evaluates every edge; no code path skips it.
    """

    def test_phase3_plan_transitions_to_consensus(self):
        graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
        plan_node = graph.get("phase3-plan")
        assert plan_node.transitions == [
            {"to": "phase3-tasks-lexicon", "condition": "always"}
        ]
        assert graph.get("phase3-tasks-lexicon").transitions[-1] == {
            "to": "phase3-understanding",
            "condition": "tasks_lexicon_action in [proceed, proceed_with_warning]",
        }
        assert graph.get("phase3-understanding").transitions == [
            {"to": "phase3-consensus", "condition": "always"}
        ]

    def test_phase3_plan_to_consensus_condition_is_always(self):
        graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
        plan_node = graph.get("phase3-plan")
        assert plan_node.transitions[0]["condition"] == "always"

    def test_staged_parallel_has_stage1_and_stage2_agents(self):
        graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
        consensus_node = graph.get("phase3-consensus")
        stage1 = [a for a in consensus_node.agents if a.get("stage", 1) == 1]
        stage2 = [a for a in consensus_node.agents if a.get("stage", 1) == 2]
        assert len(stage1) >= 2, (
            f"phase3-consensus must have ≥2 stage-1 agents (WHY3 + ASSESS2), got {len(stage1)}"
        )
        assert len(stage2) >= 1, (
            f"phase3-consensus must have ≥1 stage-2 agent (PLAN2), got {len(stage2)}"
        )

    def test_condition_evaluator_cannot_skip_always(self):
        """ConditionEvaluator must return True for 'always' — never None."""
        from harness.condition_evaluator import ConditionEvaluator
        ev = ConditionEvaluator()
        assert ev.evaluate("always", {}) is True
        # 'always' can never trigger COMMANDER dispatch (would require None return)
        assert ev.evaluate("always", {}) is not None

    def test_assess2_completed_rejection_is_not_treated_as_executor_block(
        self,
        tmp_path: Path,
    ) -> None:
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize(
            "r",
            "banzai",
            "msg",
            0,
            "phase3-consensus",
            max_iterations=5,
        )
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        state = store.load()
        state["spec_dir"] = str(spec_dir.relative_to(tmp_path))
        store.save(state)

        def consensus_result(_project_root: str, prompt: str, **_kwargs):
            if "Operate in **WHY3** mode" in prompt:
                return SquadAgentResult(
                    0,
                    {"verdict": "PASS", "state_updates": {}},
                    "",
                    1,
                    False,
                )
            if "Operate in **ASSESS2** mode" in prompt:
                (spec_dir / "implementability-report.md").write_text(
                    "# Implementability\n",
                    encoding="utf-8",
                )
                return SquadAgentResult(
                    0,
                    {
                        "verdict": "BLOCKED",
                        "state_updates": {
                            "gate_decision": "REJECTED",
                            "phase_recommendation": "phase3-how",
                            "implementability_metrics": {},
                        },
                    },
                    "Assessment completed with a critical feasibility rejection.",
                    1,
                    False,
                )
            if "Operate in **PLAN2** mode" in prompt:
                return SquadAgentResult(
                    0,
                    {"verdict": "COMPLETE", "state_updates": {}},
                    "",
                    1,
                    False,
                )
            raise AssertionError("unexpected consensus prompt")

        provider.exec_agent.side_effect = consensus_result
        result = ctrl._executors["staged_parallel"].execute(
            ctrl._graph.get("phase3-consensus"),
            store,
        )

        assert result.verdict == "FAIL"
        persisted = store.load()
        assert persisted["assess2_verdict"] == "REJECTED"
        assert persisted["gate_decision"] == "REJECTED"
        assert persisted["phase_recommendation"] == "phase3-how"
        assert any(
            "Operate in **PLAN2** mode" in call.args[1]
            for call in provider.exec_agent.call_args_list
        )


class TestSolutionPhaseOrdering:
    def test_specialists_feed_architect_before_sentinel(self):
        graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)

        specialists_node = graph.get("phase3-specialists")
        specialist_targets = [t["to"] for t in specialists_node.transitions]
        assert specialist_targets == ["phase3-how"]

        how_node = graph.get("phase3-how")
        how_targets = [t["to"] for t in how_node.transitions]
        assert how_targets == ["phase3-sentinel"]

    def test_sentinel_runs_before_plan_so_tests_become_tasks(self):
        graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)

        sentinel_node = graph.get("phase3-sentinel")
        sentinel_targets = [t["to"] for t in sentinel_node.transitions]
        assert sentinel_targets == ["phase3-plan"]


class TestAgentResultIntegrity:
    def test_provider_usage_increment_preserves_concurrent_state_mutation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        original_load = store.load
        original_increment_token_usage = store.increment_token_usage
        original_set_cancel_requested = store.set_cancel_requested
        injected = False
        mutation_requested = Event()
        mutation_complete = Event()
        mutation_errors: list[BaseException] = []

        def mutate_concurrently() -> None:
            if not mutation_requested.wait(timeout=5):
                return
            try:
                original_set_cancel_requested()
            except BaseException as exc:
                mutation_errors.append(exc)
            finally:
                mutation_complete.set()

        mutation_thread = Thread(target=mutate_concurrently)
        mutation_thread.start()

        def request_concurrent_mutation() -> None:
            nonlocal injected
            if not injected:
                injected = True
                mutation_requested.set()
                assert mutation_complete.wait(timeout=5)

        def racing_load() -> dict:
            snapshot = original_load()
            request_concurrent_mutation()
            return snapshot

        def racing_increment_token_usage(tokens: int) -> None:
            request_concurrent_mutation()
            original_increment_token_usage(tokens)

        monkeypatch.setattr(store, "load", racing_load)
        monkeypatch.setattr(
            store,
            "increment_token_usage",
            racing_increment_token_usage,
        )
        try:
            ctrl._record_provider_usage(
                SquadAgentResult(
                    exit_code=0,
                    echelon_result={"verdict": "DONE", "state_updates": {}},
                    raw_output="",
                    duration_ms=0,
                    timed_out=False,
                    token_usage=37,
                )
            )
            state = original_load()
            assert state["cancel_requested"] is True
            assert state["token_usage"] == 37
            assert not mutation_errors
        finally:
            mutation_requested.set()
            mutation_thread.join(timeout=5)
            assert not mutation_thread.is_alive()

    def test_provider_limit_without_result_fails_closed_at_preparation(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=2,
            echelon_result=None,
            raw_output="You've hit your session limit · resets 4am (Europe/Prague)",
            duration_ms=100,
            timed_out=False,
            provider_limit_message="You've hit your session limit · resets 4am (Europe/Prague)",
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-what", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        result = ctrl.run("msg", "banzai")
        state = store.load()

        assert result.status == "blocked"
        assert state["phase"] == "phase1-what"
        assert (
            state["blocked_reason"]
            == "controller_state_contract_validation_failed"
        )
        assert state["controller_contract_error"] == {
            "phase_id": "phase1-what",
            "contract": "provider",
            "contract_sha256": None,
            "json_path": "$.echelon_result",
            "validator": "echelon_result",
            "message": (
                "controller result preparation failed at "
                "$.echelon_result (echelon_result)"
            ),
        }
        assert state["recovery_instruction"] == {
            "schema_version": 1,
            "kind": "retry_phase",
            "reason_code": "controller_state_contract_validation_failed",
            "phase": "phase1-what",
            "requires_human_input": False,
        }
        assert "provider_limit_message" not in state
        assert "blocked_context" not in state
        assert "session limit" not in json.dumps(
            state["controller_contract_error"]
        )

    def test_agent_timeout_without_result_is_reported_directly(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=-9,
            echelon_result=None,
            raw_output="partial architecture output",
            duration_ms=600_004,
            timed_out=True,
            stderr="agent timed out after 600 seconds",
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-what", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        result = ctrl.run("msg", "banzai")
        state = store.load()

        assert result.status == "blocked"
        assert state["phase"] == "terminal-blocked"
        assert state["blocked_reason"] == "agent_timeout"
        assert state["recovery_instruction"] == {
            "schema_version": 1,
            "kind": "retry_phase",
            "reason_code": "agent_timeout",
            "phase": "phase1-what",
            "requires_human_input": False,
        }
        assert state["last_dispatch"]["phase_id"] == "phase1-what"
        assert "controller_contract_error" not in state

    def test_agent_phase_without_parseable_echelon_result_blocks(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result=None,
            raw_output=(
                "echelon-cartographer (CARTOGRAPHER) BLOCKED — "
                "specification authoring incomplete"
            ),
            duration_ms=100,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-what", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        result = ctrl.run("msg", "banzai")
        state = store.load()

        assert result.status == "blocked"
        assert state["phase"] == "phase1-what"
        assert state["status"] == "blocked"
        assert (
            state["blocked_reason"]
            == "controller_state_contract_validation_failed"
        )
        assert (
            state["controller_contract_error"]["contract"]
            == "provider"
        )
        assert "phase1-what" not in state.get("completed_phases", [])

    def test_banzai_agent_block_without_recommendation_awaits_human(
        self, tmp_path
    ) -> None:
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DECISION_RESOLVED",
                "state_updates": {},
                "journal_entries": [],
                "decision": {
                    "selected_option_id": None,
                    "answer_text": "Use direct Python execution without packaging.",
                    "rationale": "The request calls for the smallest executable program.",
                    "confidence": "high",
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase3-how", max_iterations=5)
        state = store.load()
        state["spec_dir"] = "specs/001-demo"
        store.save(state)
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
        (spec_dir / "unknowns.md").write_text("# Unknowns\n", encoding="utf-8")
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "BLOCKED",
                "state_updates": {},
                "journal_entries": [],
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        snapshot = store.capture_routing_snapshot(expected_phase="phase3-how")

        assert not ctrl._route_agent_block_to_commander(
            ctrl._graph.get("phase3-how"), "agent_blocked", result, snapshot
        )

        state = store.load()
        assert state["status"] == "blocked"
        assert state["phase"] == "phase3-how"
        assert state["blocked_reason"] == "agent_blocked"
        assert state["blocked_decision"]["schema_version"] == 3
        assert state["blocked_decision"]["status"] == "awaiting_human"
        assert state["blocked_decision"]["automatic_eligible"] is False
        assert state["recovery_instruction"]["kind"] == "await_human_answer"
        provider.exec_agent.assert_not_called()

    @pytest.mark.parametrize("manual_phase_run", [False, True])
    def test_executor_missing_output_uses_recovery_block(
        self,
        tmp_path: Path,
        manual_phase_run: bool,
    ) -> None:
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "output_files": ["specs/001-demo/spec.md"],
                "state_updates": {
                    "spec_status": "planned",
                    "evidence_resolution_status": "not_required",
                },
                "journal_entries": [],
            },
            raw_output="",
            duration_ms=100,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize(
            "r",
            "banzai",
            "msg",
            0,
            "phase1-what",
            max_iterations=5,
        )
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
        state = store.load()
        state["spec_id"] = "001-demo"
        state["spec_dir"] = "specs/001-demo"
        state["controller_contract_error"] = {
            "phase_id": "phase1-what",
            "contract": "preparation",
            "json_path": "$.state_updates.missing_outputs",
            "validator": "ownership",
        }
        state["recovery_instruction"] = {
            "schema_version": 1,
            "kind": "sync_runtime_then_retry",
            "reason_code": "controller_state_contract_validation_failed",
            "phase": "phase1-what",
            "requires_human_input": False,
        }
        store.save(state)

        result = (
            ctrl.run_single_phase("phase1-what", "msg", "banzai")
            if manual_phase_run
            else ctrl.run("msg", "banzai")
        )
        state = store.load()

        assert result.status == "blocked"
        assert state["phase"] == "terminal-blocked"
        assert state["blocked_reason"] == "missing_phase_outputs"
        assert state["missing_outputs"] == ["requirements-overview.md"]
        assert state["phase_output_recovery"] == {
            "phase": "phase1-what",
            "missing_outputs": ["requirements-overview.md"],
            "prior_state_updates": {
                "spec_status": "planned",
                "evidence_resolution_status": "not_required",
            },
        }
        assert "controller_contract_error" not in state
        assert state["recovery_instruction"] == {
            "schema_version": 1,
            "kind": "retry_phase",
            "reason_code": "missing_phase_outputs",
            "phase": "phase1-what",
            "requires_human_input": False,
        }
        assert "phase1-what" not in state.get("completed_phases", [])

    def test_successful_advance_clears_controller_recovery_instruction(
        self,
        tmp_path,
    ):
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "banzai",
            "msg",
            0,
            "phase1-what",
            max_iterations=5,
        )
        state = store.load()
        state["status"] = "running"
        state["controller_contract_error"] = {"phase_id": "phase1-what"}
        state["recovery_instruction"] = {
            "schema_version": 1,
            "kind": "sync_runtime_then_retry",
            "reason_code": "controller_state_contract_validation_failed",
            "phase": "phase1-what",
            "requires_human_input": False,
        }
        store.save(state)

        _install_empty_routed_completion(
            ctrl,
            store,
            from_phase="phase1-what",
            to_phase="phase1-why1",
        )

        advanced = store.load()
        assert "controller_contract_error" not in advanced
        assert "recovery_instruction" not in advanced

    def test_phase1_what_missing_result_does_not_apply_recovery_state(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result=None,
            raw_output="connection closed after CARTOGRAPHER wrote spec artifacts",
            duration_ms=100,
            timed_out=False,
        )
        spec_dir = tmp_path / "specs" / "001-demo-notes"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo Notes\n", encoding="utf-8")
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-what", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        with patch.object(ctrl, "_current_git_branch", return_value="001-demo-notes"):
            result = ctrl.run("msg", "banzai")
        state = store.load()

        assert result.status == "blocked"
        assert state["phase"] == "phase1-what"
        assert (
            state["blocked_reason"]
            == "controller_state_contract_validation_failed"
        )
        assert "spec_id" not in state
        assert "spec_dir" not in state
        assert "published_spec_dir" not in state
        assert "feature_branch" not in state
        assert "cartographer_resume_existing_spec" not in state
        assert "phase1-what" not in state.get("completed_phases", [])

    def test_phase4_document_blocks_when_phase_a_build_inputs_are_missing(
        self, tmp_path,
    ):
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase4-document", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        for name in ("plan.md", "research.md", "data-model.md", "tasks.md"):
            (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
        state = store.load()
        state["spec_id"] = "001-demo"
        state["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(state)

        result = ctrl.run("msg", "banzai")
        state = store.load()

        assert result.status == "blocked"
        assert state["phase"] == "terminal-blocked"
        assert state["blocked_reason"] == "phase_a_readiness_failed"
        assert "spec.md absent" in "\n".join(state["phase_a_readiness_blockers"])

    def test_phase4_document_completes_when_phase_a_build_inputs_exist(
        self, tmp_path,
    ):
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase4-document", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        _write_phase_a_build_inputs(spec_dir)
        checkpoint_ledger = spec_dir / ".echelon" / "checkpoints.json"
        checkpoint_ledger.parent.mkdir()
        checkpoint_ledger.write_text(
            '{"spec_id": "001-demo", "checkpoints": []}\n',
            encoding="utf-8",
        )
        state = store.load()
        state["spec_id"] = "001-demo"
        state["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(state)
        kb_report = tmp_path / "runs" / "r" / "kb-apply-report.yaml"
        kb_report.parent.mkdir(parents=True)
        kb_report.write_text("status: degraded\n", encoding="utf-8")

        result = ctrl.run("msg", "banzai")

        assert result.status == "done"
        published_dir = tmp_path / "specs" / "001-demo"
        assert (published_dir / "spec.md").exists()
        assert (published_dir / "plan.md").exists()
        assert (published_dir / "tasks.md").exists()
        assert (
            published_dir / "constitution.md"
        ).read_text(encoding="utf-8") == "# Constitution\n\nReal project rules.\n"
        assert (published_dir / "ARTIFACTS.md").exists()
        assert (published_dir / "squad-report.md").exists()
        assert not (published_dir / ".echelon").exists()
        assert (published_dir / "kb" / "kb-apply-report.yaml").read_text(
            encoding="utf-8"
        ) == "status: degraded\n"
        history = json.loads((published_dir / "run-history.json").read_text(encoding="utf-8"))
        assert history["runs"][-1]["run_id"] == "r"
        assert history["runs"][-1]["phase"] == "A"
        assert history["runs"][-1]["status"] == "done"
        state = store.load()
        assert state["published_spec_dir"] == "specs/001-demo"

    def test_phase4_document_generates_final_overview_and_plan_conformance(
        self, tmp_path,
    ):
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r", "banzai", "msg", 0, "phase4-document", max_iterations=5
        )
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        _write_phase_a_build_inputs(spec_dir, include_fr=True)
        for name in (
            "00-overview.md",
            "plan-conformance.md",
            "plan-conformance.json",
        ):
            (spec_dir / name).unlink()
        state = store.load()
        state["spec_id"] = "001-demo"
        state["spec_dir"] = "runs/run-test/specs/001-demo"
        state["implementability_metrics"] = {
            "implementability_ready": 10,
            "implementability_needs_clarification": 0,
            "implementability_blocked": 0,
        }
        store.save(state)

        result = ctrl.run("msg", "banzai")

        assert result.status == "done"
        published_dir = tmp_path / "specs" / "001-demo"
        assert (published_dir / "00-overview.md").exists()
        assert (published_dir / "plan-conformance.md").exists()
        conformance = json.loads(
            (published_dir / "plan-conformance.json").read_text(encoding="utf-8")
        )
        assert conformance == {
            "status": "pass",
            "findings": [],
            "sources": [
                "spec.md",
                "requirements-overview.md",
                "mvp-scope.md",
                "plan.md",
                "tasks.md",
                "dependencies.md",
                "critical-path.md",
            ],
        }
        assert store.load()["published_spec_dir"] == "specs/001-demo"

    def test_manual_phase4_recovery_preserves_blocked_run_state(
        self, tmp_path,
    ):
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "terminal-blocked")
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        _write_phase_a_build_inputs(spec_dir, include_fr=True)
        for name in (
            "00-overview.md",
            "plan-conformance.md",
            "plan-conformance.json",
        ):
            (spec_dir / name).unlink()
        state = store.load()
        completed_before = [
            "phase1-constitution",
            "phase1-what",
            "phase1-understanding",
            "phase1-why2",
            "phase1-lexicon-derive",
            "phase1-lexicon",
            "phase3-plan",
            "phase3-consensus",
        ]
        state.update(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": "phase_a_readiness_failed",
                "phase_a_readiness_blockers": [
                    "plan-conformance.md absent",
                    "plan-conformance.json absent",
                ],
                "spec_id": "001-demo",
                "spec_dir": "runs/run-test/specs/001-demo",
                "completed_phases": completed_before.copy(),
                "phase_dispatch_counts": {"phase3-consensus": 2},
                "token_usage": 12_345,
                "cost_usd": 9.25,
            }
        )
        store.save(state)

        result = ctrl.run(
            "msg",
            "banzai",
            next_phase_override="phase4-document",
        )

        assert result.status == "done"
        recovered = store.load()
        assert recovered["token_usage"] == 12_345
        assert recovered["cost_usd"] == 9.25
        assert "phase3-consensus" in recovered["completed_phases"]
        assert "phase_a_readiness_blockers" not in recovered
        assert recovered["published_spec_dir"] == "specs/001-demo"

    def test_phase4_document_publishes_complete_artifacts_to_existing_slugged_spec(
        self, tmp_path,
    ):
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase4-document", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        active_spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001"
        active_spec_dir.mkdir(parents=True)
        _write_phase_a_build_inputs(active_spec_dir, prefix="active ")
        (active_spec_dir / "contracts").mkdir()
        (active_spec_dir / "contracts" / "api.md").write_text("# Contract\n", encoding="utf-8")

        published_dir = tmp_path / "specs" / "001-themed-ascii-animation"
        published_dir.mkdir(parents=True)
        (published_dir / "spec.md").write_text("# stale spec\n", encoding="utf-8")
        (published_dir / "manual-note.md").write_text("# Keep me\n", encoding="utf-8")

        state = store.load()
        state["spec_id"] = "001"
        state["spec_dir"] = "runs/run-test/specs/001"
        store.save(state)

        result = ctrl.run("msg", "banzai")
        state = store.load()

        assert result.status == "done"
        assert (published_dir / "spec.md").read_text(encoding="utf-8") == "# active spec.md\n"
        assert (published_dir / "plan.md").exists()
        assert (published_dir / "research.md").exists()
        assert (published_dir / "data-model.md").exists()
        assert (published_dir / "tasks.md").exists()
        assert (
            published_dir / "constitution.md"
        ).read_text(encoding="utf-8") == "# Constitution\n\nReal project rules.\n"
        assert (published_dir / "contracts" / "api.md").exists()
        assert (published_dir / "manual-note.md").exists()
        assert (published_dir / "ARTIFACTS.md").exists()
        assert (published_dir / "squad-report.md").exists()
        assert (published_dir / "run-history.json").exists()
        assert state["published_spec_dir"] == "specs/001-themed-ascii-animation"

    def test_done_run_reconciles_newer_run_local_artifacts_to_published_spec(
        self, tmp_path,
    ):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "DONE", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        active_spec_dir = tmp_path / "squad" / "run-test" / "specs" / "001-demo"
        active_spec_dir.mkdir(parents=True)
        _write_phase_a_build_inputs(active_spec_dir, prefix="active ")
        (active_spec_dir / "user-intent.md").write_text(
            "# User Intent\n\nfresh run-local artifact\n",
            encoding="utf-8",
        )

        published_dir = tmp_path / "specs" / "001-demo"
        published_dir.mkdir(parents=True)
        (published_dir / "spec.md").write_text("# stale spec\n", encoding="utf-8")

        state = store.load()
        state["status"] = "done"
        state["spec_id"] = "001-demo"
        state["spec_dir"] = "squad/run-test/specs/001-demo"
        state["published_spec_dir"] = "specs/001-demo"
        store.save(state)

        result = ctrl.run("msg", "banzai")
        state = store.load()

        assert result.status == "done"
        assert (published_dir / "spec.md").read_text(encoding="utf-8") == "# active spec.md\n"
        assert (published_dir / "user-intent.md").read_text(encoding="utf-8") == (
            "# User Intent\n\nfresh run-local artifact\n"
        )
        assert (published_dir / "ARTIFACTS.md").exists()
        assert (published_dir / "squad-report.md").exists()
        history = json.loads((published_dir / "run-history.json").read_text(encoding="utf-8"))
        assert history["runs"][-1]["run_id"] == "r"
        assert state["published_spec_dir"] == "specs/001-demo"

    @staticmethod
    def _phase_a_publication_staging_fixture(
        tmp_path: Path,
    ) -> tuple[SquadController, SquadStateStore, SquadAgentResult, Path, Path]:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "banzai",
            "msg",
            0,
            "phase4-document",
            max_iterations=5,
            implementation_targets=["sources/app"],
        )
        _mark_constitution_complete(tmp_path, store)
        active_spec_dir = tmp_path / "squad" / "run-test" / "specs" / "001"
        active_spec_dir.mkdir(parents=True)
        _write_phase_a_build_inputs(
            active_spec_dir,
            prefix="active ",
            include_fr=True,
        )
        (active_spec_dir / "contracts").mkdir()
        (active_spec_dir / "contracts" / "api.md").write_text(
            "# Active API contract\n",
            encoding="utf-8",
        )
        runtime_file = active_spec_dir / ".echelon" / "checkpoints.json"
        runtime_file.parent.mkdir()
        runtime_file.write_text('{"private": true}\n', encoding="utf-8")

        published_spec_dir = (
            tmp_path / "specs" / "001-themed-ascii-animation"
        )
        published_spec_dir.mkdir(parents=True)
        (published_spec_dir / "spec.md").write_text(
            "# stale published spec\n",
            encoding="utf-8",
        )
        (published_spec_dir / "manual-note.md").write_text(
            "# Preserve this destination-only note\n",
            encoding="utf-8",
        )
        (published_spec_dir / ".echelon").mkdir()
        (published_spec_dir / ".echelon" / "local.json").write_text(
            '{"destination": true}\n',
            encoding="utf-8",
        )

        state = store.load()
        state["spec_id"] = "001"
        state["spec_dir"] = str(active_spec_dir.relative_to(tmp_path))
        state["published_spec_dir"] = str(
            published_spec_dir.relative_to(tmp_path)
        )
        store.save(state)
        kb_report = tmp_path / "runs" / "r" / "kb-apply-report.yaml"
        kb_report.parent.mkdir(parents=True)
        kb_report.write_text("status: degraded\n", encoding="utf-8")
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        return ctrl, store, result, active_spec_dir, published_spec_dir

    @staticmethod
    def _attach_ready_phase_a_product_inputs(
        tmp_path: Path,
        ctrl: SquadController,
        store: SquadStateStore,
        active_spec_dir: Path,
    ) -> tuple[Path, str]:
        from echelon.product_inputs import (
            apply_product_input_updates,
            immutable_product_input_tree_digest,
            parse_input_declaration,
            resolve_product_inputs,
        )

        source = tmp_path / "requirements.md"
        source.write_text("A normative product requirement.\n", encoding="utf-8")
        resolution = resolve_product_inputs(
            tmp_path,
            ctrl._squad_dir,
            [parse_input_declaration("requirement:requirements.md")],
        )
        unit_id = json.loads(
            resolution.catalog_path.read_text(encoding="utf-8")
        )["units"][0]["id"]
        (active_spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=build req=FR-001 "
            "depends=none target=sources/app\n",
            encoding="utf-8",
        )
        apply_product_input_updates(
            resolution.traceability_path,
            [
                {
                    "input_unit_id": unit_id,
                    "disposition": "included",
                    "rationale": "Mapped before final documentation.",
                    "spec_ids": ["FR-001"],
                    "task_ids": ["T-001"],
                    "targets": ["sources/app"],
                }
            ],
        )
        product_inputs = resolution.state_payload(tmp_path)
        product_inputs["tree_hash"] = immutable_product_input_tree_digest(
            resolution.inputs_dir
        )
        state = store.load()
        state["product_inputs"] = product_inputs
        store.save(state)
        return resolution.inputs_dir, str(product_inputs["tree_hash"])

    @staticmethod
    def _visible_tree_bytes(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    @pytest.mark.parametrize(
        "fault_point",
        [
            "active_overlay",
            "product_evidence",
            "constitution",
            "kb",
            "history",
            "report",
            "artifact_index",
            "metadata",
            "readiness",
        ],
    )
    def test_phase_a_publication_staging_failure_keeps_visible_spec_identical(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fault_point: str,
    ) -> None:
        import echelon.context_metadata as context_metadata
        import echelon.kb_proposals as kb_proposals
        import harness.squad as squad_module
        from harness.phase_a_readiness import PhaseAReadinessResult
        from harness.squad import _PhaseAReadinessCommitError

        ctrl, store, result, _, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        before = self._visible_tree_bytes(published)

        if fault_point == "active_overlay":
            original = ctrl._copy_spec_tree

            def fault(*args, **kwargs):
                original(*args, **kwargs)
                raise OSError("injected active overlay failure")

            monkeypatch.setattr(ctrl, "_copy_spec_tree", fault)
        elif fault_point == "product_evidence":
            original = ctrl._publish_product_input_evidence

            def fault(*args, **kwargs):
                original(*args, **kwargs)
                raise OSError("injected product evidence failure")

            monkeypatch.setattr(ctrl, "_publish_product_input_evidence", fault)
        elif fault_point == "constitution":
            original = ctrl._publish_constitution_snapshot

            def fault(*args, **kwargs):
                original(*args, **kwargs)
                raise OSError("injected constitution failure")

            monkeypatch.setattr(ctrl, "_publish_constitution_snapshot", fault)
        elif fault_point == "kb":
            monkeypatch.setattr(
                kb_proposals,
                "publish_kb_reports",
                lambda *_args, **_kwargs: None,
            )
        elif fault_point == "history":
            original = squad_module.append_phase_a_run

            def fault(*args, **kwargs):
                original(*args, **kwargs)
                raise OSError("injected history failure")

            monkeypatch.setattr(squad_module, "append_phase_a_run", fault)
        elif fault_point == "report":
            original = ctrl._write_squad_report

            def fault(*args, **kwargs):
                original(*args, **kwargs)
                raise OSError("injected report failure")

            monkeypatch.setattr(ctrl, "_write_squad_report", fault)
        elif fault_point == "artifact_index":
            original = squad_module.write_artifact_index

            def fault(*args, **kwargs):
                original(*args, **kwargs)
                raise OSError("injected artifact index failure")

            monkeypatch.setattr(squad_module, "write_artifact_index", fault)
        elif fault_point == "metadata":
            original = context_metadata.write_feature_metadata

            def fault(*args, **kwargs):
                original(*args, **kwargs)
                raise OSError("injected metadata failure")

            monkeypatch.setattr(context_metadata, "write_feature_metadata", fault)
        else:
            monkeypatch.setattr(
                squad_module,
                "validate_phase_a_readiness",
                lambda *_: PhaseAReadinessResult(
                    ready=False,
                    blockers=["injected readiness failure"],
                    missing={},
                    ready_spec_dir=None,
                ),
            )

        with pytest.raises(_PhaseAReadinessCommitError):
            ctrl._prepare_external_phase_effects(
                result,
                "phase4-document",
                store.load(),
                manual_phase_run=False,
            )

        assert self._visible_tree_bytes(published) == before
        assert "pending_external_publication" not in store.load()

    def test_phase_a_publication_staging_rejects_symlinked_constitution_source(
        self,
        tmp_path: Path,
    ) -> None:
        from harness.squad import _PhaseAReadinessCommitError

        ctrl, store, result, _, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        before = self._visible_tree_bytes(published)
        constitution = tmp_path / ".echelon" / "constitution.md"
        outside = tmp_path.parent / f"{tmp_path.name}-constitution.md"
        outside.write_text("# External constitution\n", encoding="utf-8")
        constitution.unlink()
        constitution.symlink_to(outside)

        with pytest.raises(_PhaseAReadinessCommitError):
            ctrl._prepare_external_phase_effects(
                result,
                "phase4-document",
                store.load(),
                manual_phase_run=False,
            )

        assert self._visible_tree_bytes(published) == before
        assert "pending_external_publication" not in store.load()

    def test_phase_a_publication_staging_rejects_absolute_run_id_kb_source(
        self,
        tmp_path: Path,
    ) -> None:
        from harness.squad import _PhaseAReadinessCommitError

        ctrl, store, result, _, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        before = self._visible_tree_bytes(published)
        outside_run = tmp_path.parent / f"{tmp_path.name}-external-run"
        outside_run.mkdir()
        (outside_run / "kb-apply-report.yaml").write_text(
            "status: external\n",
            encoding="utf-8",
        )
        state = store.load()
        state["run_id"] = str(outside_run)

        with pytest.raises(_PhaseAReadinessCommitError):
            ctrl._prepare_external_phase_effects(
                result,
                "phase4-document",
                state,
                manual_phase_run=False,
            )

        assert self._visible_tree_bytes(published) == before
        assert "pending_external_publication" not in store.load()

    @pytest.mark.parametrize("source_kind", ["regular", "symlink"])
    def test_phase_a_publication_staging_rejects_kb_source_created_by_helper(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        source_kind: str,
    ) -> None:
        import echelon.kb_proposals as kb_proposals
        from harness.squad import _PhaseAReadinessCommitError

        ctrl, store, result, _, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        before = self._visible_tree_bytes(published)
        run_dir = tmp_path / "runs" / "r"
        usage = run_dir / "kb-usage.yaml"
        assert not usage.exists()
        outside = tmp_path.parent / f"{tmp_path.name}-kb-usage.yaml"
        outside.write_text("status: external\n", encoding="utf-8")
        original = kb_proposals.publish_kb_reports

        def swap_then_publish(*args, **kwargs):
            if source_kind == "symlink":
                usage.symlink_to(outside)
            else:
                usage.write_bytes(outside.read_bytes())
            return original(*args, **kwargs)

        monkeypatch.setattr(
            kb_proposals,
            "publish_kb_reports",
            swap_then_publish,
        )

        with pytest.raises(_PhaseAReadinessCommitError):
            ctrl._prepare_external_phase_effects(
                result,
                "phase4-document",
                store.load(),
                manual_phase_run=False,
            )

        assert self._visible_tree_bytes(published) == before
        assert "pending_external_publication" not in store.load()

    def test_phase_a_publication_staging_manifest_is_exact_and_preserves_note(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store, result, active, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        before = self._visible_tree_bytes(published)

        prepared = ctrl._prepare_external_phase_effects(
            result,
            "phase4-document",
            store.load(),
            manual_phase_run=False,
        )

        assert prepared is not None
        assert self._visible_tree_bytes(published) == before
        manifest_path = (
            ctrl._squad_dir
            / ".publication-outbox"
            / prepared.marker.transaction_id
            / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        targets = {operation["target"] for operation in manifest["operations"]}
        prefix = "specs/001-themed-ascii-animation/"
        active_files = {
            prefix + path.relative_to(active).as_posix()
            for path in active.rglob("*")
            if path.is_file() and ".echelon" not in path.parts
        }
        generated = {
            prefix + name
            for name in (
                "constitution.md",
                "targets.yml",
                "run-history.json",
                "squad-report.md",
                "ARTIFACTS.md",
                "feature-metadata.yml",
            )
        }
        assert targets == active_files | generated | {
            prefix + "kb/kb-apply-report.yaml"
        }
        assert prefix + "manual-note.md" not in targets
        assert not any("/.echelon/" in target for target in targets)

        prepared.publish()

        assert (published / "manual-note.md").read_text(encoding="utf-8") == (
            "# Preserve this destination-only note\n"
        )
        assert (published / "spec.md").read_text(encoding="utf-8").startswith(
            "# active spec.md"
        )

    def test_phase4_read_only_product_inputs_use_authenticated_snapshot(
        self,
        tmp_path: Path,
    ) -> None:
        from echelon.product_inputs import immutable_product_input_tree_digest

        ctrl, store, result, active, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        _, expected_hash = self._attach_ready_phase_a_product_inputs(
            tmp_path, ctrl, store, active
        )

        prepared = ctrl._prepare_external_phase_effects(
            result,
            "phase4-document",
            store.load(),
            manual_phase_run=False,
        )

        assert prepared is not None
        snapshot = prepared._transaction_root / "work/product-inputs"
        assert immutable_product_input_tree_digest(snapshot) == expected_hash
        assert not (published / "inputs/manifest.json").exists()
        prepared.publish()
        assert immutable_product_input_tree_digest(published / "inputs") == expected_hash

    def test_controller_tree_copy_preserves_all_modes_under_restrictive_umask(
        self,
        tmp_path: Path,
    ) -> None:
        import os
        import stat

        ctrl, _ = _controller(tmp_path)
        source = tmp_path / "mode-source"
        nested = source / "private-bin"
        nested.mkdir(parents=True)
        private = nested / "private.txt"
        executable = nested / "tool"
        private.write_bytes(b"private")
        executable.write_bytes(b"#!/bin/sh\n")
        source.chmod(0o751)
        nested.chmod(0o710)
        private.chmod(0o600)
        executable.chmod(0o751)
        destination = tmp_path / "mode-destination"
        previous_umask = os.umask(0o077)
        try:
            ctrl._copy_controller_tree(
                source,
                destination,
                exclude_echelon=False,
            )
        finally:
            os.umask(previous_umask)

        assert stat.S_IMODE(destination.stat().st_mode) == 0o751
        assert stat.S_IMODE((destination / "private-bin").stat().st_mode) == 0o710
        assert stat.S_IMODE((destination / "private-bin/private.txt").stat().st_mode) == 0o600
        assert stat.S_IMODE((destination / "private-bin/tool").stat().st_mode) == 0o751

    def test_phase4_publication_repairs_mode_only_file_drift(
        self,
        tmp_path: Path,
    ) -> None:
        import stat

        ctrl, store, result, active, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        active_spec = active / "spec.md"
        published_spec = published / "spec.md"
        published_spec.write_bytes(active_spec.read_bytes())
        active_spec.chmod(0o600)
        published_spec.chmod(0o644)

        prepared = ctrl._prepare_external_phase_effects(
            result,
            "phase4-document",
            store.load(),
            manual_phase_run=False,
        )

        assert prepared is not None
        operation = next(
            item
            for item in prepared._manifest["operations"]
            if item["target"] == "specs/001-themed-ascii-animation/spec.md"
        )
        assert operation["postimage"]["mode"] == 0o600
        prepared.publish()
        assert stat.S_IMODE(published_spec.stat().st_mode) == 0o600

    @pytest.mark.parametrize("tamper", ["bytes", "mode"])
    def test_phase4_rejects_unauthenticated_live_product_inputs_before_publish(
        self,
        tmp_path: Path,
        tamper: str,
    ) -> None:
        from harness.squad import _ProductInputCommitError

        ctrl, store, result, active, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        inputs, _ = self._attach_ready_phase_a_product_inputs(
            tmp_path, ctrl, store, active
        )
        target = inputs / "manifest.json"
        if tamper == "bytes":
            target.write_bytes(target.read_bytes() + b" ")
        else:
            target.chmod(0o600)
        before = self._visible_tree_bytes(published)

        with pytest.raises(_ProductInputCommitError) as caught:
            ctrl._prepare_external_phase_effects(
                result,
                "phase4-document",
                store.load(),
                manual_phase_run=False,
            )

        assert "tree hash drift" in caught.value.reason
        assert self._visible_tree_bytes(published) == before

    @pytest.mark.parametrize("race", ["source", "snapshot"])
    def test_phase4_rejects_product_input_copy_race_before_publish(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        race: str,
    ) -> None:
        from harness.squad import _ProductInputCommitError

        ctrl, store, result, active, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        inputs, _ = self._attach_ready_phase_a_product_inputs(
            tmp_path, ctrl, store, active
        )
        before = self._visible_tree_bytes(published)
        original_copy = ctrl._copy_controller_tree

        def race_copy(source, destination, *, exclude_echelon):
            copied = original_copy(
                source, destination, exclude_echelon=exclude_echelon
            )
            if source == inputs and destination.name == "product-inputs":
                target = (
                    inputs / "manifest.json"
                    if race == "source"
                    else destination / "manifest.json"
                )
                target.write_bytes(target.read_bytes() + b" ")
            return copied

        monkeypatch.setattr(ctrl, "_copy_controller_tree", race_copy)

        with pytest.raises(_ProductInputCommitError) as caught:
            ctrl._prepare_external_phase_effects(
                result,
                "phase4-document",
                store.load(),
                manual_phase_run=False,
            )

        assert (
            "changed during staging" in caught.value.reason
            or "tree hash drift" in caught.value.reason
        )
        assert self._visible_tree_bytes(published) == before

    @pytest.mark.parametrize("retry_tamper", [None, "bytes", "mode"])
    def test_phase4_publication_retry_reauthenticates_live_product_inputs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        retry_tamper: str | None,
    ) -> None:
        from echelon.product_inputs import immutable_product_input_tree_digest

        ctrl, store, _, active, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        inputs, expected_hash = self._attach_ready_phase_a_product_inputs(
            tmp_path, ctrl, store, active
        )
        state = store.load()
        state["phase"] = "DONE"
        state["status"] = "done"
        store.save(state)
        original_publish = PreparedSquadPublication.publish
        calls = 0

        def fail_first(publication, fault_hook=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise PublicationError("publish_io")
            return original_publish(publication, fault_hook=fault_hook)

        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            fail_first,
        )

        readiness = ctrl._publish_terminal_phase_a_artifacts_if_available()
        assert readiness is not None and not readiness.ready
        before = self._visible_tree_bytes(published)
        if retry_tamper == "bytes":
            target = inputs / "manifest.json"
            target.write_bytes(target.read_bytes() + b" ")
        elif retry_tamper == "mode":
            (inputs / "manifest.json").chmod(0o600)

        recovery = ctrl._drain_pending_controller_completion()

        if retry_tamper is None:
            assert recovery.recovered
            assert immutable_product_input_tree_digest(published / "inputs") == expected_hash
            assert PENDING_EXTERNAL_PUBLICATION_KEY not in store.load()
        else:
            assert not recovery.recovered
            assert self._visible_tree_bytes(published) == before
            assert PENDING_EXTERNAL_PUBLICATION_KEY in store.load()

    def test_terminal_reconciliation_commits_marker_before_visible_write(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _, _, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        state = store.load()
        state["phase"] = "DONE"
        state["status"] = "done"
        store.save(state)
        before = self._visible_tree_bytes(published)
        publish = PreparedSquadPublication.publish
        calls: list[str] = []

        def marker_guard(publication):
            assert (
                store.load()[PENDING_EXTERNAL_PUBLICATION_KEY]
                == publication.marker.to_dict()
            )
            assert self._visible_tree_bytes(published) == before
            calls.append("publish")
            return publish(publication)

        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            marker_guard,
        )

        readiness = ctrl._publish_terminal_phase_a_artifacts_if_available()

        assert readiness is not None
        assert readiness.ready is True
        assert calls == ["publish"]
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in store.load()
        assert (published / "spec.md").read_text(encoding="utf-8").startswith(
            "# active spec.md"
        )

    def test_exact_terminal_inventory_suppresses_fresh_reconciliation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _, _, _ = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        state = store.load()
        state["phase"] = "DONE"
        state["status"] = "done"
        store.save(state)
        first = ctrl._publish_terminal_phase_a_artifacts_if_available()
        assert first is not None and first.ready
        terminal = store.load()["last_terminal_completion"]
        assert len(terminal["phase_a_active_source_sha256"]) == 64
        assert (
            len(terminal["phase_a_published_postimage_sha256"])
            == 64
        )

        fresh, _ = _controller(tmp_path)
        stage = MagicMock(
            side_effect=AssertionError(
                "exact terminal inventory was restaged"
            )
        )
        monkeypatch.setattr(
            fresh,
            "_prepare_external_phase_effects",
            stage,
        )

        readiness = (
            fresh._publish_terminal_phase_a_artifacts_if_available()
        )

        assert readiness is not None and readiness.ready
        assert stage.call_count == 0

    @pytest.mark.parametrize("drift", ["active", "published"])
    def test_terminal_inventory_drift_restages_and_refreshes_provenance(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        drift: str,
    ) -> None:
        ctrl, store, _, active, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        state = store.load()
        state["phase"] = "DONE"
        state["status"] = "done"
        store.save(state)
        first = ctrl._publish_terminal_phase_a_artifacts_if_available()
        assert first is not None and first.ready
        prior = dict(store.load()["last_terminal_completion"])
        target = active / "spec.md" if drift == "active" else published / "spec.md"
        target.write_text(
            f"# {drift} inventory drift\n\nFR-001\n",
            encoding="utf-8",
        )

        fresh, _ = _controller(tmp_path)
        publish = PreparedSquadPublication.publish
        publishes: list[str] = []

        def observe(publication):
            publishes.append(publication.marker.transaction_id)
            return publish(publication)

        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            observe,
        )
        readiness = (
            fresh._publish_terminal_phase_a_artifacts_if_available()
        )

        assert readiness is not None and readiness.ready
        assert len(publishes) == 1
        refreshed = store.load()["last_terminal_completion"]
        assert refreshed["completion_id"] != prior["completion_id"]
        assert (
            refreshed["phase_a_active_source_sha256"],
            refreshed["phase_a_published_postimage_sha256"],
        ) == fresh._phase_a_inventory_digests(store.load())

    def test_running_terminal_reconciliation_reloads_state_before_done_save(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _, _, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        state = store.load()
        state["phase"] = "DONE"
        state["status"] = "running"
        store.save(state)
        monkeypatch.setattr(
            ctrl,
            "_guard_spec_lexicon_evidence",
            lambda phase: phase,
        )
        monkeypatch.setattr(
            ctrl,
            "_guard_understanding_evidence",
            lambda phase: phase,
        )
        monkeypatch.setattr(
            ctrl,
            "_apply_phase_recommendation_guard",
            lambda phase: phase,
        )
        monkeypatch.setattr(
            ctrl,
            "_guard_constitution_provenance",
            lambda phase: phase,
        )
        monkeypatch.setattr(ctrl, "_ensure_telemetry_manifest", lambda: None)

        result = ctrl.run("msg", "banzai")

        assert result.status == "done"
        completed = store.load()
        assert completed["status"] == "done"
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in completed
        assert (published / "spec.md").read_text(encoding="utf-8").startswith(
            "# active spec.md"
        )

    def test_terminal_marker_post_save_exception_continues_publication(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _, _, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        state = store.load()
        state["phase"] = "DONE"
        state["status"] = "done"
        store.save(state)
        save = store._save_unlocked
        injected = False

        def save_marker_then_raise(next_state):
            nonlocal injected
            saved = save(next_state)
            if (
                not injected
                and PENDING_EXTERNAL_PUBLICATION_KEY in next_state
            ):
                injected = True
                raise OSError("injected post-save marker exception")
            return saved

        monkeypatch.setattr(
            store,
            "_save_unlocked",
            save_marker_then_raise,
        )

        result = ctrl.run("msg", "banzai")

        assert injected is True
        assert result.status == "done"
        completed = store.load()
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in completed
        assert "external_publication_failure" not in completed
        assert (published / "spec.md").read_text(encoding="utf-8").startswith(
            "# active spec.md"
        )

    def test_terminal_reconciliation_interruption_recovers_without_diagnostic_overwrite(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _, _, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        state = store.load()
        state["phase"] = "DONE"
        state["status"] = "done"
        store.save(state)
        publish = PreparedSquadPublication.publish

        def interrupt(publication):
            def fault(position: int) -> None:
                if position == 1:
                    raise RuntimeError("terminal publication interruption")

            return publish(publication, fault_hook=fault)

        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            interrupt,
        )
        checkpoint = MagicMock(
            side_effect=AssertionError(
                "terminal reconciliation replayed routed success work"
            )
        )
        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            checkpoint,
        )

        first = ctrl.run("msg", "banzai")

        failed = store.load()
        assert first.status == "blocked"
        assert failed["phase"] == "DONE"
        assert failed["blocked_reason"] == "external_publication_pending"
        assert failed["external_publication_failure"]["code"] == "publish_io"
        assert PENDING_EXTERNAL_PUBLICATION_KEY in failed
        assert "phase_a_readiness_failed" not in json.dumps(failed)

        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            publish,
        )
        recovered = ctrl.run("msg", "banzai")

        assert recovered.status == "done"
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in store.load()
        assert "external_publication_failure" not in store.load()
        assert checkpoint.call_count == 0
        assert (published / "spec.md").read_text(encoding="utf-8").startswith(
            "# active spec.md"
        )

    def test_terminal_post_handoff_failure_preserves_completion_authority(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _, _, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        state = store.load()
        state["phase"] = "DONE"
        state["status"] = "done"
        store.save(state)
        monkeypatch.setattr(
            ctrl,
            "_apply_controller_completion_effect",
            MagicMock(side_effect=CompletionError("stage_io")),
        )

        first = ctrl.run("msg", "banzai")

        failed = store.load()
        assert first.status == "blocked"
        assert failed["phase"] == "DONE"
        assert failed["blocked_reason"] == "controller_completion_pending"
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in failed
        assert PENDING_CONTROLLER_COMPLETION_KEY in failed
        assert failed["controller_completion_failure"]["code"] == "stage_io"
        assert "phase_a_readiness_failed" not in json.dumps(failed)

        fresh, _ = _controller(tmp_path)
        recovered = fresh.run("msg", "banzai")

        assert recovered.status == "done"
        assert recovered.phase == "DONE"
        completed = store.load()
        assert PENDING_CONTROLLER_COMPLETION_KEY not in completed
        assert "controller_completion_failure" not in completed
        assert (published / "spec.md").read_text(encoding="utf-8").startswith(
            "# active spec.md"
        )

    def test_terminal_inventory_failure_retains_complete_marker(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _, _, _ = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        state = store.load()
        state["phase"] = "DONE"
        state["status"] = "done"
        store.save(state)
        inventory = ctrl._phase_a_inventory_digests
        calls = 0

        def fail_final_inventory(current_state):
            nonlocal calls
            calls += 1
            if calls > 1:
                return None
            return inventory(current_state)

        monkeypatch.setattr(
            ctrl,
            "_phase_a_inventory_digests",
            fail_final_inventory,
        )

        first = ctrl.run("msg", "banzai")

        failed = store.load()
        assert first.status == "blocked"
        assert failed["phase"] == "DONE"
        assert failed[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == (
            "complete"
        )
        assert failed["controller_completion_failure"]["code"] == (
            "receipts_mismatch"
        )
        assert "last_terminal_completion" not in failed

        fresh, _ = _controller(tmp_path)
        recovered = fresh.run("msg", "banzai")

        assert recovered.status == "done"
        completed = store.load()
        assert PENDING_CONTROLLER_COMPLETION_KEY not in completed
        assert len(
            completed["last_terminal_completion"][
                "phase_a_active_source_sha256"
            ]
        ) == 64
        assert len(
            completed["last_terminal_completion"][
                "phase_a_published_postimage_sha256"
            ]
        ) == 64

    def test_phase_a_publication_staging_uses_staged_product_evidence(
        self,
        tmp_path: Path,
    ) -> None:
        from echelon.product_inputs import (
            parse_input_declaration,
            resolve_product_inputs,
        )

        ctrl, store, _, active, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        product_source = tmp_path / "requirements.md"
        product_source.write_text(
            "A normative product requirement.\n",
            encoding="utf-8",
        )
        resolution = resolve_product_inputs(
            tmp_path,
            ctrl._squad_dir,
            [parse_input_declaration("requirement:requirements.md")],
        )
        unit_id = json.loads(
            resolution.catalog_path.read_text(encoding="utf-8")
        )["units"][0]["id"]
        (active / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=build req=FR-001 "
            "depends=none target=sources/app\n",
            encoding="utf-8",
        )
        state = store.load()
        state["product_inputs"] = resolution.state_payload(tmp_path)
        store.save(state)
        stale_evidence = published / "inputs" / "stale-evidence.txt"
        stale_evidence.parent.mkdir()
        stale_evidence.write_text("obsolete\n", encoding="utf-8")
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "product_input_updates": [
                    {
                        "input_unit_id": unit_id,
                        "disposition": "included",
                        "rationale": "Mapped during final documentation.",
                        "spec_ids": ["FR-001"],
                        "task_ids": ["T-001"],
                        "targets": ["sources/app"],
                    }
                ],
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        visible_traceability_before = resolution.traceability_path.read_bytes()

        prepared = ctrl._prepare_external_phase_effects(
            result,
            "phase4-document",
            store.load(),
            manual_phase_run=False,
        )

        assert prepared is not None
        assert (
            resolution.traceability_path.read_bytes()
            == visible_traceability_before
        )
        assert not (published / "inputs" / "traceability.json").exists()
        manifest = json.loads(
            (
                ctrl._squad_dir
                / ".publication-outbox"
                / prepared.marker.transaction_id
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )
        targets = {operation["target"] for operation in manifest["operations"]}
        assert (
            resolution.traceability_path.relative_to(tmp_path).as_posix()
            in targets
        )
        assert (
            "specs/001-themed-ascii-animation/inputs/traceability.json"
            in targets
        )
        stale_operation = next(
            operation
            for operation in manifest["operations"]
            if operation["target"]
            == "specs/001-themed-ascii-animation/inputs/stale-evidence.txt"
        )
        assert stale_operation["action"] == "delete"

        prepared.publish()

        visible_ledger = json.loads(
            resolution.traceability_path.read_text(encoding="utf-8")
        )
        published_ledger = json.loads(
            (published / "inputs" / "traceability.json").read_text(
                encoding="utf-8"
            )
        )
        assert visible_ledger == published_ledger
        assert visible_ledger["requirements"][0]["disposition"] == "included"
        assert not stale_evidence.exists()

    @pytest.mark.parametrize("phase", ["phase3-plan", "phase4-document"])
    def test_manual_replay_prepares_no_external_publication(
        self,
        tmp_path: Path,
        phase: str,
    ) -> None:
        ctrl, store, result, _, published = (
            self._phase_a_publication_staging_fixture(tmp_path)
        )
        before = self._visible_tree_bytes(published)

        prepared = ctrl._prepare_external_phase_effects(
            result,
            phase,
            store.load(),
            manual_phase_run=True,
        )

        assert prepared is None
        assert self._visible_tree_bytes(published) == before

    def test_publication_staging_keeps_target_materialization_out_of_checkpoint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        materialize = MagicMock(
            side_effect=AssertionError(
                "checkpoint attempted an untracked targets.yml write"
            )
        )
        monkeypatch.setattr(
            ctrl,
            "_materialize_implementation_targets",
            materialize,
        )

        assert ctrl._checkpoint_successful_phase(
            "phase1-what",
            "phase1-why1",
        )
        materialize.assert_not_called()

    @pytest.mark.parametrize("fault_position", [0, 1, 2, 3])
    def test_external_publication_fault_boundary_recovers_idempotently(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fault_position: int,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        prepared, targets = _sealed_publication_fixture(ctrl)
        marker = _install_publication_marker(store, prepared)
        original_publish = PreparedSquadPublication.publish

        def faulted_publish(publication):
            def fault(position: int) -> None:
                if position == fault_position:
                    raise RuntimeError("injected publication boundary")

            return original_publish(publication, fault_hook=fault)

        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            faulted_publish,
        )

        assert ctrl._publish_and_finalize(prepared, marker) is False
        failed = store.load()
        assert failed[PENDING_EXTERNAL_PUBLICATION_KEY] == marker
        assert failed["status"] == "blocked"
        assert failed["blocked_reason"] == "external_publication_pending"
        assert failed["external_publication_failure"]["code"] == "publish_io"
        transaction_root = (
            ctrl._squad_dir
            / ".publication-outbox"
            / prepared.marker.transaction_id
        )
        assert transaction_root.is_dir()

        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            original_publish,
        )
        del ctrl
        fresh, _ = _controller(tmp_path)
        assert fresh._recover_pending_external_publication() is True

        recovered = store.load()
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in recovered
        assert "external_publication_failure" not in recovered
        assert recovered["status"] == "running"
        assert targets["replace"].read_text(encoding="utf-8") == (
            "new replace\n"
        )
        assert targets["create"].read_text(encoding="utf-8") == "new create\n"
        assert not targets["delete"].exists()
        assert not transaction_root.exists()

    def test_external_publication_retry_rejects_drifted_completed_postimage(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        prepared, targets = _sealed_publication_fixture(ctrl)
        marker = _install_publication_marker(store, prepared)
        publish = PreparedSquadPublication.publish

        def stop_after_first(publication):
            def fault(position: int) -> None:
                if position == 1:
                    raise RuntimeError("injected retry boundary")

            return publish(publication, fault_hook=fault)

        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            stop_after_first,
        )
        assert ctrl._publish_and_finalize(prepared, marker) is False
        assert targets["replace"].read_text(encoding="utf-8") == (
            "new replace\n"
        )
        targets["replace"].write_text(
            "drifted after partial publication\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            publish,
        )

        del ctrl
        fresh, _ = _controller(tmp_path)
        assert fresh._recover_pending_external_publication() is False
        failed = store.load()
        assert failed[PENDING_EXTERNAL_PUBLICATION_KEY] == marker
        assert failed["external_publication_failure"]["code"] == (
            "target_drift"
        )
        assert targets["replace"].read_text(encoding="utf-8") == (
            "drifted after partial publication\n"
        )

    def test_external_publication_finalize_save_failure_recovers_after_postimages(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        prepared, targets = _sealed_publication_fixture(ctrl)
        marker = _install_publication_marker(store, prepared)
        complete = store.complete_external_publication
        attempts = 0

        def fail_first_clear(value):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError("injected marker-clear save failure")
            return complete(value)

        monkeypatch.setattr(
            store,
            "complete_external_publication",
            fail_first_clear,
        )

        assert ctrl._publish_and_finalize(prepared, marker) is False
        failed = store.load()
        assert failed[PENDING_EXTERNAL_PUBLICATION_KEY] == marker
        assert failed["external_publication_failure"]["code"] == (
            "state_finalize"
        )
        assert targets["replace"].read_text(encoding="utf-8") == (
            "new replace\n"
        )
        assert targets["create"].read_text(encoding="utf-8") == "new create\n"
        assert not targets["delete"].exists()

        assert ctrl._recover_pending_external_publication() is True
        assert attempts == 2
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in store.load()

    def test_external_publication_never_publishes_without_exact_state_marker(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        prepared, targets = _sealed_publication_fixture(ctrl)

        assert ctrl._publish_and_finalize(
            prepared,
            prepared.marker.to_dict(),
        ) is False
        assert targets["replace"].read_text(encoding="utf-8") == (
            "old replace\n"
        )
        assert not targets["create"].exists()
        assert targets["delete"].read_text(encoding="utf-8") == (
            "old delete\n"
        )
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in store.load()

    def test_external_publication_rejects_a_stage_not_named_by_the_marker(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        authorized, _ = _sealed_publication_fixture(ctrl)
        marker = _install_publication_marker(store, authorized)
        unauthorized, _ = _sealed_publication_fixture(ctrl)
        publish = MagicMock()
        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            publish,
        )

        assert ctrl._publish_and_finalize(unauthorized, marker) is False
        publish.assert_not_called()
        assert store.load()[PENDING_EXTERNAL_PUBLICATION_KEY] == marker

    def test_external_publication_finalize_exception_after_clear_accepts_completion(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        prepared, targets = _sealed_publication_fixture(ctrl)
        marker = _install_publication_marker(store, prepared)
        complete = store.complete_external_publication

        def clear_then_raise(value):
            complete(value)
            raise OSError("simulated post-save exception")

        monkeypatch.setattr(
            store,
            "complete_external_publication",
            clear_then_raise,
        )

        assert ctrl._publish_and_finalize(prepared, marker) is True
        completed = store.load()
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in completed
        assert "external_publication_failure" not in completed
        assert targets["replace"].read_text(encoding="utf-8") == (
            "new replace\n"
        )
        assert not (
            ctrl._squad_dir
            / ".publication-outbox"
            / prepared.marker.transaction_id
        ).exists()

    @pytest.mark.parametrize(
        ("damage", "expected_code"),
        [
            ("target_drift", "target_drift"),
            ("stage_missing", "stage_missing"),
            ("stage_corrupt", "stage_corrupt"),
            ("manifest_mismatch", "manifest_mismatch"),
            ("manifest_invalid", "manifest_invalid"),
        ],
    )
    def test_external_publication_recovery_failures_are_bounded(
        self,
        tmp_path: Path,
        damage: str,
        expected_code: str,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        prepared, targets = _sealed_publication_fixture(ctrl)
        marker = _install_publication_marker(store, prepared)
        transaction_root = (
            ctrl._squad_dir
            / ".publication-outbox"
            / prepared.marker.transaction_id
        )
        manifest = transaction_root / "manifest.json"
        if damage == "target_drift":
            targets["replace"].write_text("unexpected\n", encoding="utf-8")
        elif damage == "stage_missing":
            prepared.discard()
        elif damage == "stage_corrupt":
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            staged_ref = next(
                operation["staged"]
                for operation in payload["operations"]
                if operation["action"] == "write"
            )
            (transaction_root / staged_ref).write_text(
                "corrupt staged bytes\n",
                encoding="utf-8",
            )
        elif damage == "manifest_mismatch":
            manifest.write_bytes(manifest.read_bytes() + b" ")
        else:
            corrupt = b"{not-json"
            manifest.write_bytes(corrupt)
            marker = {
                **marker,
                "manifest_sha256": hashlib.sha256(corrupt).hexdigest(),
            }
            state = store.load()
            state[PENDING_EXTERNAL_PUBLICATION_KEY] = marker
            store.save(state)

        assert ctrl._recover_pending_external_publication() is False

        failed = store.load()
        assert failed[PENDING_EXTERNAL_PUBLICATION_KEY] == marker
        assert failed["status"] == "blocked"
        assert failed["blocked_reason"] == "external_publication_pending"
        assert failed["external_publication_failure"] == {
            "schema_version": 1,
            "code": expected_code,
            "resume_status": "running",
            "resume_blocked_reason": None,
        }
        assert expected_code in json.dumps(failed)
        assert str(transaction_root) not in json.dumps(failed)

    @pytest.mark.parametrize(
        "marker",
        [
            None,
            {
                "schema_version": 1,
                "transaction_id": "bad",
                "manifest_sha256": "b" * 64,
            },
        ],
    )
    @pytest.mark.parametrize("entrypoint", ["normal", "manual"])
    def test_malformed_publication_marker_blocks_with_bounded_diagnostic(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        marker: object,
        entrypoint: str,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        state = store.load()
        state[PENDING_EXTERNAL_PUBLICATION_KEY] = marker
        store.save(state)
        callback = MagicMock(
            side_effect=AssertionError(
                "entrypoint ran with a malformed publication marker"
            )
        )
        if entrypoint == "normal":
            monkeypatch.setattr(ctrl, "_run_locked", callback)
            result = ctrl.run("msg", "banzai")
        else:
            monkeypatch.setattr(
                ctrl,
                "_run_single_phase_locked",
                callback,
            )
            result = ctrl.run_single_phase(
                "phase1-what",
                "msg",
                "banzai",
            )

        failed = store.load()
        assert result.status == "blocked"
        assert callback.call_count == 0
        assert failed[PENDING_EXTERNAL_PUBLICATION_KEY] == marker
        assert failed["blocked_reason"] == (
            "controller_completion_pending"
        )
        assert failed["controller_completion_failure"] == {
            "schema_version": 1,
            "code": "completion_missing",
            "resume_status": "running",
            "resume_blocked_reason": None,
        }
        assert "external_publication_failure" not in failed

    @pytest.mark.parametrize("entrypoint", ["normal", "manual"])
    def test_pending_external_publication_recovers_before_entrypoint_status_logic(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        entrypoint: str,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        _configure_tasks_lexicon_route(ctrl, store, monkeypatch)
        publication, targets = _sealed_publication_fixture(ctrl)
        node = ctrl._graph.get("phase3-tasks-lexicon")
        agent_result = ctrl._executors[
            "deterministic_lexicon"
        ].execute(node, store)
        snapshot = store.capture_routing_snapshot(
            expected_phase=node.id,
        )
        prepared_result = ctrl._prepare_phase_result(
            node,
            agent_result,
            snapshot,
        )
        decision = ctrl._coordinate_transition_routing(
            node,
            prepared_result,
            snapshot,
            additional_state_updates={
                PENDING_EXTERNAL_PUBLICATION_KEY: (
                    publication.marker.to_dict()
                ),
            },
        )
        store.advance(node.id, decision.to_phase, decision)
        calls: list[str] = []

        def after_recovery(*_args, **_kwargs):
            assert PENDING_EXTERNAL_PUBLICATION_KEY not in store.load()
            assert PENDING_CONTROLLER_COMPLETION_KEY not in store.load()
            assert store.load()["last_dispatch"][
                "post_dispatch_complete"
            ] is True
            assert targets["create"].read_text(encoding="utf-8") == (
                "new create\n"
            )
            calls.append(entrypoint)
            return SquadResult.from_state(store.load())

        if entrypoint == "normal":
            monkeypatch.setattr(ctrl, "_run_locked", after_recovery)
            ctrl.run("msg", "banzai")
        else:
            monkeypatch.setattr(
                ctrl,
                "_run_single_phase_locked",
                after_recovery,
            )
            ctrl.run_single_phase("phase1-what", "msg", "banzai")

        assert calls == [entrypoint]

    @pytest.mark.parametrize("entrypoint", ["normal", "manual"])
    def test_publication_without_completion_blocks_before_entrypoint_logic(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        entrypoint: str,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        prepared, _ = _sealed_publication_fixture(ctrl)
        marker = _install_publication_marker(store, prepared)
        callback = MagicMock(
            side_effect=AssertionError("entrypoint ran before recovery")
        )
        publish = MagicMock(
            side_effect=AssertionError(
                "publication ran without completion authority"
            )
        )
        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            publish,
        )
        if entrypoint == "normal":
            monkeypatch.setattr(ctrl, "_run_locked", callback)
            result = ctrl.run("msg", "banzai")
        else:
            monkeypatch.setattr(
                ctrl,
                "_run_single_phase_locked",
                callback,
            )
            result = ctrl.run_single_phase(
                "phase1-what",
                "msg",
                "banzai",
            )

        assert callback.call_count == 0
        assert result.status == "blocked"
        assert result.phase == "phase1-what"
        assert publish.call_count == 0
        failed = store.load()
        assert failed[PENDING_EXTERNAL_PUBLICATION_KEY] == marker
        assert failed["controller_completion_failure"]["code"] == (
            "completion_missing"
        )
        assert "external_publication_failure" not in failed

    def test_explicit_null_completion_retains_publication_and_blocks(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        publication, _ = _sealed_publication_fixture(ctrl)
        marker = _install_publication_marker(store, publication)
        state = store.load()
        state[PENDING_CONTROLLER_COMPLETION_KEY] = None
        store.save(state)
        publish = MagicMock(
            side_effect=AssertionError(
                "malformed completion authorized publication"
            )
        )
        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            publish,
        )
        runner = MagicMock(
            side_effect=AssertionError(
                "entrypoint ran with malformed completion"
            )
        )
        monkeypatch.setattr(ctrl, "_run_locked", runner)

        result = ctrl.run("msg", "banzai")

        failed = store.load()
        assert result.status == "blocked"
        assert runner.call_count == 0
        assert publish.call_count == 0
        assert failed[PENDING_CONTROLLER_COMPLETION_KEY] is None
        assert failed[PENDING_EXTERNAL_PUBLICATION_KEY] == marker
        assert failed["controller_completion_failure"]["code"] == (
            "intent_invalid"
        )

    def test_missing_completion_stage_retains_both_authorities(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        _configure_tasks_lexicon_route(ctrl, store, monkeypatch)
        publication, _ = _sealed_publication_fixture(ctrl)
        node = ctrl._graph.get("phase3-tasks-lexicon")
        result = ctrl._executors["deterministic_lexicon"].execute(
            node,
            store,
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase=node.id,
        )
        prepared_result = ctrl._prepare_phase_result(
            node,
            result,
            snapshot,
        )
        decision = ctrl._coordinate_transition_routing(
            node,
            prepared_result,
            snapshot,
            additional_state_updates={
                PENDING_EXTERNAL_PUBLICATION_KEY: (
                    publication.marker.to_dict()
                ),
            },
        )
        store.advance(node.id, decision.to_phase, decision)
        authorized = store.load()
        completion_marker = authorized[
            PENDING_CONTROLLER_COMPLETION_KEY
        ]
        staged_completion = load_prepared_controller_completion(
            tmp_path,
            ctrl._squad_dir,
            completion_marker,
        )
        staged_completion.discard()
        publish = MagicMock(
            side_effect=AssertionError(
                "missing completion stage authorized publication"
            )
        )
        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            publish,
        )
        runner = MagicMock(
            side_effect=AssertionError(
                "entrypoint ran with missing completion stage"
            )
        )
        monkeypatch.setattr(ctrl, "_run_locked", runner)

        result = ctrl.run("msg", "banzai")

        failed = store.load()
        assert result.status == "blocked"
        assert runner.call_count == 0
        assert publish.call_count == 0
        assert failed[PENDING_CONTROLLER_COMPLETION_KEY] == (
            completion_marker
        )
        assert failed[PENDING_EXTERNAL_PUBLICATION_KEY] == (
            publication.marker.to_dict()
        )
        assert failed["controller_completion_failure"]["code"] == (
            "stage_missing"
        )

    def test_routed_publication_orders_marker_before_publish_and_success_work(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        _configure_tasks_lexicon_route(ctrl, store, monkeypatch)
        prepared, targets = _sealed_publication_fixture(ctrl)
        calls: list[str] = []
        route = ctrl._coordinate_transition_routing
        advance = store.advance
        publish = PreparedSquadPublication.publish
        handoff = store.handoff_external_publication

        def stage(*_args, **_kwargs):
            calls.append("stage")
            return prepared

        def record_route(*args, **kwargs):
            calls.append("route")
            return route(*args, **kwargs)

        def record_advance(*args, **kwargs):
            receipt = advance(*args, **kwargs)
            assert (
                store.load()[PENDING_EXTERNAL_PUBLICATION_KEY]
                == prepared.marker.to_dict()
            )
            assert PENDING_CONTROLLER_COMPLETION_KEY in store.load()
            calls.append("advance")
            return receipt

        def record_publish(publication):
            assert (
                store.load()[PENDING_EXTERNAL_PUBLICATION_KEY]
                == prepared.marker.to_dict()
            )
            assert store.load()[PENDING_CONTROLLER_COMPLETION_KEY][
                "step"
            ] == "awaiting_publication"
            calls.append("publish")
            return publish(publication)

        def record_handoff(marker, completion):
            result = handoff(marker, completion)
            assert PENDING_EXTERNAL_PUBLICATION_KEY not in store.load()
            assert store.load()[PENDING_CONTROLLER_COMPLETION_KEY][
                "step"
            ] != "awaiting_publication"
            calls.append("handoff")
            return result

        monkeypatch.setattr(ctrl, "_prepare_external_phase_effects", stage)
        monkeypatch.setattr(
            ctrl,
            "_coordinate_transition_routing",
            record_route,
        )
        monkeypatch.setattr(store, "advance", record_advance)
        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            record_publish,
        )
        monkeypatch.setattr(
            store,
            "handoff_external_publication",
            record_handoff,
        )

        ctrl.run_single_phase(
            "phase3-tasks-lexicon",
            "msg",
            "banzai",
        )

        assert calls == [
            "stage",
            "route",
            "advance",
            "publish",
            "handoff",
        ]
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in store.load()
        assert PENDING_CONTROLLER_COMPLETION_KEY not in store.load()
        assert store.load()["last_dispatch"][
            "post_dispatch_complete"
        ] is True
        assert targets["replace"].read_text(encoding="utf-8") == (
            "new replace\n"
        )

    @pytest.mark.parametrize("failure", ["stale", "save"])
    def test_routed_precommit_failure_discards_unreferenced_stage_without_publish(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        failure: str,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        _configure_tasks_lexicon_route(ctrl, store, monkeypatch)
        prepared, targets = _sealed_publication_fixture(ctrl)
        transaction_root = (
            ctrl._squad_dir
            / ".publication-outbox"
            / prepared.marker.transaction_id
        )
        monkeypatch.setattr(
            ctrl,
            "_prepare_external_phase_effects",
            lambda *_args, **_kwargs: prepared,
        )
        success_calls: list[str] = []
        monkeypatch.setattr(
            ctrl,
            "_apply_declared_phase_timing_transition",
            lambda *_: success_calls.append("timing"),
        )
        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            lambda *_: success_calls.append("checkpoint"),
        )
        if failure == "stale":
            construct = ctrl._construct_routing_decision_or_block

            def stale_after_seal(*args, **kwargs):
                decision = construct(*args, **kwargs)
                assert decision is not None
                concurrent = store.load()
                concurrent["concurrent_marker"] = "kept"
                store.save(concurrent)
                return decision

            monkeypatch.setattr(
                ctrl,
                "_construct_routing_decision_or_block",
                stale_after_seal,
            )
        else:
            save = store._save_unlocked
            injected = False

            def fail_marker_save(state, **kwargs):
                nonlocal injected
                if (
                    not injected
                    and PENDING_EXTERNAL_PUBLICATION_KEY in state
                ):
                    injected = True
                    raise OSError("injected routing save failure")
                return save(state, **kwargs)

            monkeypatch.setattr(
                store,
                "_save_unlocked",
                fail_marker_save,
            )

        ctrl.run("msg", "banzai")

        assert PENDING_EXTERNAL_PUBLICATION_KEY not in store.load()
        assert not transaction_root.exists()
        assert targets["replace"].read_text(encoding="utf-8") == (
            "old replace\n"
        )
        assert not targets["create"].exists()
        assert targets["delete"].read_text(encoding="utf-8") == (
            "old delete\n"
        )
        assert success_calls == []

    @pytest.mark.parametrize("entrypoint", ["normal", "manual"])
    @pytest.mark.parametrize("fault_position", [0, 1, 2, 3])
    def test_crash_shaped_retry_defers_success_work_until_durable_clear(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        entrypoint: str,
        fault_position: int,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        _configure_tasks_lexicon_route(ctrl, store, monkeypatch)
        prepared, targets = _sealed_publication_fixture(ctrl)
        monkeypatch.setattr(
            ctrl,
            "_prepare_external_phase_effects",
            lambda *_args, **_kwargs: prepared,
        )
        publish = PreparedSquadPublication.publish

        def fail_after_operation(publication):
            def fault(position: int) -> None:
                if position == fault_position:
                    raise RuntimeError("simulated crash")

            return publish(publication, fault_hook=fault)

        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            fail_after_operation,
        )

        if entrypoint == "normal":
            first = ctrl.run("msg", "banzai")
        else:
            first = ctrl.run_single_phase(
                "phase3-tasks-lexicon",
                "msg",
                "banzai",
            )

        assert first.status == "blocked"
        assert PENDING_EXTERNAL_PUBLICATION_KEY in store.load()
        assert PENDING_CONTROLLER_COMPLETION_KEY in store.load()
        completion_id = store.load()[
            PENDING_CONTROLLER_COMPLETION_KEY
        ]["completion_id"]

        monkeypatch.setattr(
            PreparedSquadPublication,
            "publish",
            publish,
        )
        del ctrl
        fresh, _ = _controller(tmp_path)
        locked_runner = MagicMock(
            side_effect=lambda *_args, **_kwargs: SquadResult.from_state(
                store.load()
            )
        )
        if entrypoint == "normal":
            monkeypatch.setattr(fresh, "_run_locked", locked_runner)
            fresh.run("msg", "banzai")
            assert locked_runner.call_count == 1
        else:
            monkeypatch.setattr(
                fresh,
                "_run_single_phase_locked",
                locked_runner,
            )
            fresh.run_single_phase(
                "phase3-tasks-lexicon",
                "msg",
                "banzai",
            )
            assert locked_runner.call_count == 0

        recovered = store.load()
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in recovered
        assert PENDING_CONTROLLER_COMPLETION_KEY not in recovered
        assert recovered["last_dispatch"]["dispatch_id"] == completion_id
        assert recovered["last_dispatch"][
            "post_dispatch_complete"
        ] is True
        assert targets["replace"].read_text(encoding="utf-8") == (
            "new replace\n"
        )
        assert targets["create"].read_text(encoding="utf-8") == (
            "new create\n"
        )
        assert not targets["delete"].exists()

    def test_checkpoint_plan_semi_auto_routes_without_commander_judgment(self, tmp_path):
        _disable_lexicon_gate(tmp_path)
        provider = MagicMock()
        provider.exec_agent.side_effect = AssertionError(
            "checkpoint-plan should not dispatch COMMANDER judgment in semi"
        )
        ctrl, store = _controller(tmp_path, provider=provider, mode="semi")
        store.initialize("r", "semi", "msg", 0, "checkpoint-plan", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)

        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        _write_phase_a_build_inputs(spec_dir)
        state = store.load()
        state["spec_id"] = "001-demo"
        state["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(state)

        result = ctrl.run("msg", "semi")

        assert result.status == "done"
        assert provider.exec_agent.call_count == 0


class TestCartographerResumeGuard:
    def test_phase1_what_prompt_blocks_duplicate_specify_on_resume(self, tmp_path):
        graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
        squad_dir = tmp_path / "runs" / "spec-test"
        staging_dir = squad_dir / "staging"
        staging_dir.mkdir(parents=True)
        existing_spec = tmp_path / "specs" / "072-pr-pipeline-fix"
        existing_spec.mkdir(parents=True)
        (existing_spec / "spec.md").write_text("# Existing spec\n", encoding="utf-8")
        executor = AgentExecutor(
            _mock_provider(),
            graph,
            EXT_ROOT / "runtime",
            tmp_path,
            squad_dir,
        )

        prompt = executor._assemble_prompt(
            graph.get("phase1-what"),
            {
                "squad_dir": str(squad_dir),
                "staging_dir": str(staging_dir),
                "cartographer_resume_existing_spec": True,
                "spec_dir": "specs/072-pr-pipeline-fix",
                "feature_branch": "072-pr-pipeline-fix",
            },
        )

        assert "## CARTOGRAPHER Resume Guard" in prompt
        assert "Do NOT create, switch, rename, or discover a branch or spec directory" in prompt
        assert "Existing spec_dir: specs/072-pr-pipeline-fix" in prompt
        assert "Existing feature_branch: 072-pr-pipeline-fix" in prompt


class TestSquadControllerBasics:
    def test_prepared_identity_preserves_retarget_inputs_and_re_policy(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        ctrl._implementation_targets = ["apps/web"]
        replacement_dir = store.squad_dir
        prepared_product_inputs = {
            "inputs_dir": "squad/run-test/inputs",
            "manifest": "squad/run-test/inputs/manifest.json",
            "manifest_hash": "a" * 64,
        }
        prepared_retarget = {
            "operation_id": "rt-controller-1",
            "baseline_run_id": "squad-base",
            "replacement_run_id": "run-test",
            "status": "checkpointed",
        }
        prepared = {
            "run_id": "run-test",
            "status": "preparing",
            "phase": "phase0-constitution",
            "user_message": "Original request",
            "autonomy_mode": "autonomous",
            "implementation_targets": ["apps/web"],
            "spec_id": "001-demo",
            "spec_number": "001",
            "spec_dir": "squad/run-test/specs/001-demo",
            "published_spec_dir": "specs/001-demo",
            "feature_branch": "001-demo",
            "phase_a_default_branch": "main",
            "phase_a_base_commit": "b" * 40,
            "specify_feature_directory": "squad/run-test/specs/001-demo",
            "retarget": prepared_retarget,
            "product_inputs": prepared_product_inputs,
            "ignore_re": False,
            "requested_re_sources": ["api"],
        }
        store.save(prepared)
        baseline_state = tmp_path / "squad" / "squad-base" / "state.json"
        baseline_state.parent.mkdir(parents=True)
        baseline_state.write_text('{"immutable": true}\n', encoding="utf-8")
        captured: dict[str, object] = {}

        def capture_re_context(
            project_root: Path,
            run_dir: Path,
            *,
            ignore: bool,
            implementation_targets: list[str] | None = None,
            re_sources: list[str] | None = None,
        ) -> dict[str, object]:
            captured.update(
                {
                    "project_root": project_root,
                    "run_dir": run_dir,
                    "ignore": ignore,
                    "implementation_targets": implementation_targets,
                    "re_sources": re_sources,
                }
            )
            return {"status": "absent", "generation": 0, "artifacts": {}}

        monkeypatch.setattr(squad_module, "attach_published_re_context", capture_re_context)
        monkeypatch.setattr(ctrl, "_publish_terminal_phase_a_artifacts_if_available", lambda: None)

        result = ctrl.run("replacement argument must not win", "semi", next_phase_override="DONE")

        state = store.load()
        assert result.status == "done"
        assert state["run_id"] == "run-test"
        assert state["retarget"] == prepared_retarget
        assert state["product_inputs"] == prepared_product_inputs
        assert state["ignore_re"] is False
        assert state["requested_re_sources"] == ["api"]
        assert state["user_message"] == "Original request"
        assert state["autonomy_mode"] == "autonomous"
        assert captured["implementation_targets"] == ["apps/web"]
        assert captured["re_sources"] == ["api"]
        assert baseline_state.read_text(encoding="utf-8") == '{"immutable": true}\n'

    def test_generation_change_does_not_mutate_attached_spec_context(self, tmp_path, monkeypatch):
        _disable_lexicon_gate(tmp_path)
        provider = _mock_quality_first_flow_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        monkeypatch.setattr(
            ctrl,
            "_lexicon_gate_config",
            lambda: {
                "lexicon_gate": {
                    "enabled": False,
                    "spec_enabled": False,
                }
            },
        )
        store.initialize(
            "r", "brownfield", "msg", 0, "phase1-tracker",
            spec_authoring_mode="perfectionist",
        )
        _mark_constitution_complete(tmp_path, store)
        (ctrl._squad_dir / "constitution.draft.md").write_text(
            "# Constitution\n\nReal project rules.\n", encoding="utf-8"
        )
        state = store.load()
        state["re_generation"] = 1
        state["spec_dir"] = "specs/001-test"
        state["autonomy_mode"] = "banzai"
        store.save(state)
        spec_dir = tmp_path / "specs" / "001-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(_valid_lexicon_spec(), encoding="utf-8")
        (spec_dir / "requirements-overview.md").write_text("# Overview\n", encoding="utf-8")
        _install_passing_understanding(monkeypatch)
        monkeypatch.setattr(
            ctrl, "_publish_terminal_phase_a_artifacts_if_available", lambda: None
        )
        _write_re_index_generation(tmp_path, 2)

        result = ctrl.run("msg", "banzai")

        assert result.status == "done"
        state = store.load()
        assert state.get("blocked_reason") is None
        assert state["re_generation"] == 1
        assert provider.exec_agent.called

    def test_generation_change_does_not_block_manual_spec_phase(self, tmp_path):
        provider = _mock_provider("ALIGNED")
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "brownfield", "msg", 0, "phase1-tracker")
        _mark_constitution_complete(tmp_path, store)
        state = store.load()
        state["re_generation"] = 1
        store.save(state)
        _write_re_index_generation(tmp_path, 2)

        result = ctrl.run_single_phase("phase1-tracker", "msg", "banzai")

        assert result.status == "running"
        state = store.load()
        assert state.get("blocked_reason") is None
        assert state["re_generation"] == 1
        assert provider.exec_agent.called

    def test_legacy_generation_state_is_not_synchronized_during_spec_run(self, tmp_path, monkeypatch):
        _disable_lexicon_gate(tmp_path)
        provider = _mock_quality_first_flow_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        monkeypatch.setattr(
            ctrl,
            "_lexicon_gate_config",
            lambda: {"lexicon_gate": {"enabled": False, "spec_enabled": False}},
        )
        store.initialize(
            "r", "brownfield", "msg", 0, "phase1-tracker",
            spec_authoring_mode="perfectionist",
        )
        _mark_constitution_complete(tmp_path, store)
        (ctrl._squad_dir / "constitution.draft.md").write_text(
            "# Constitution\n\nReal project rules.\n", encoding="utf-8"
        )
        state = store.load()
        state["re_generation"] = 1
        state["spec_dir"] = "specs/001-test"
        state["autonomy_mode"] = "banzai"
        store.save(state)
        spec_dir = tmp_path / "specs" / "001-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(_valid_lexicon_spec(), encoding="utf-8")
        (spec_dir / "requirements-overview.md").write_text("# Overview\n", encoding="utf-8")
        _install_passing_understanding(monkeypatch)
        monkeypatch.setattr(
            ctrl, "_publish_terminal_phase_a_artifacts_if_available", lambda: None
        )
        _write_re_index_generation(
            tmp_path,
            2,
            published_from_run=ctrl._squad_dir.name,
        )

        result = ctrl.run("msg", "banzai")

        assert result.status != "blocked"
        state = store.load()
        assert state["re_generation"] == 1
        assert state.get("blocked_reason") is None
        assert "re_generation_expected" not in state
        assert "re_generation_actual" not in state
        assert provider.exec_agent.called

    def test_fresh_run_detects_project_mode_separately_from_autonomy_mode(self, tmp_path):
        for i in range(6):
            (tmp_path / f"module_{i}.py").write_text("pass\n", encoding="utf-8")

        ctrl, store = _controller(tmp_path, mode="banzai")

        result = ctrl.run("msg", "banzai", next_phase_override="DONE")

        assert result.status == "done"
        state = store.load()
        assert state["mode"] == "brownfield"
        assert state["autonomy_mode"] == "banzai"

    def test_brownfield_discovery_does_not_run_re_controller(
        self,
        tmp_path,
        monkeypatch,
    ):
        provider = MagicMock()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=50,
            timed_out=False,
        )
        graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
        squad_dir = tmp_path / "squad" / "run-test"
        squad_dir.mkdir(parents=True, exist_ok=True)
        (squad_dir / "staging").mkdir(exist_ok=True)
        store = SquadStateStore(squad_dir)
        store.initialize("r", "brownfield", "msg", 0, "phase1-discover", autonomy_mode="banzai")
        executor = AgentExecutor(
            provider,
            graph,
            EXT_ROOT / "runtime",
            tmp_path,
            squad_dir,
        )

        executor.execute(graph.get("phase1-discover"), store)

        assert provider.exec_agent.call_count == 1
        state = store.load()
        assert "golddigger_status" not in state

    def test_spec_controller_has_no_nested_re_dispatch_recovery(
        self, tmp_path
    ):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "brownfield", "msg", 0, "phase1-discover")
        for _ in range(6):
            store.increment_phase_dispatch_count("phase1-discover")
        re_state_path = ctrl._squad_dir / "re" / "state.json"
        re_state_path.parent.mkdir(parents=True, exist_ok=True)
        re_state_path.write_text(
            json.dumps(
                {
                    "status": "blocked",
                    "phase": "re-extract-2-specify",
                    "blocked_reason": "re_quality_repair_modified_non_target_output",
                }
            ),
            encoding="utf-8",
        )

        assert not hasattr(ctrl, "_reset_discovery_dispatches_for_pending_recovery")
        assert store.get_phase_dispatch_count("phase1-discover") == 6

    def test_discovery_dispatch_count_remains_for_non_re_failure(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "brownfield", "msg", 0, "phase1-discover")
        store.increment_phase_dispatch_count("phase1-discover")
        re_state_path = ctrl._squad_dir / "re" / "state.json"
        re_state_path.parent.mkdir(parents=True, exist_ok=True)
        re_state_path.write_text(
            json.dumps({"status": "done", "phase": "re-extract-7-constitute"}),
            encoding="utf-8",
        )

        assert not hasattr(ctrl, "_reset_discovery_dispatches_for_pending_recovery")
        assert store.get_phase_dispatch_count("phase1-discover") == 1

    def test_discovery_ignores_legacy_re_plan_state(
        self,
        tmp_path,
        monkeypatch,
    ):
        provider = MagicMock()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=50,
            timed_out=False,
        )
        graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
        squad_dir = tmp_path / "squad" / "run-test"
        squad_dir.mkdir(parents=True, exist_ok=True)
        (squad_dir / "staging").mkdir(exist_ok=True)
        store = SquadStateStore(squad_dir)
        store.initialize("r", "brownfield", "msg", 0, "phase1-discover", autonomy_mode="banzai")
        executor = AgentExecutor(
            provider,
            graph,
            EXT_ROOT / "runtime",
            tmp_path,
            squad_dir,
        )

        executor.execute(graph.get("phase1-discover"), store)

        assert "golddigger_status" not in store.load()
        assert provider.exec_agent.call_count == 1

    def test_starts_at_entry_phase(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "DONE")
        result = ctrl.run("msg", "banzai")
        assert result.status == "done"

    def test_cancel_stops_loop(self, tmp_path):
        """SIGINT (self._cancelled flag) stops the loop mid-run."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "init")
        ctrl._cancelled = True   # simulate SIGINT received mid-run
        result = ctrl.run("msg", "banzai")
        assert result.status == "interrupted"
        state = store.load()
        assert state["status"] == "interrupted"
        assert state["phase"] == "init"
        assert state["interrupted_phase"] == "init"

    def test_cancel_after_agent_returns_prevents_blocked_decision(self, tmp_path):
        """A deferred Ctrl-C wins over an agent's trailing BLOCKED envelope."""
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-discover")

        def interrupted_agent(*_args, **_kwargs):
            ctrl._cancelled = True
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "BLOCKED",
                    "state_updates": {},
                    "journal_entries": [],
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )

        provider.exec_agent.side_effect = interrupted_agent

        result = ctrl.run("msg", "banzai")

        state = store.load()
        assert result.status == "interrupted"
        assert state["status"] == "interrupted"
        assert state["phase"] == "phase1-discover"
        assert state["interrupted_phase"] == "phase1-discover"
        assert "blocked_decision" not in state

    def test_bare_agent_block_is_retryable_not_a_commander_decision(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "BLOCKED",
                "state_updates": {},
                "journal_entries": [],
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-discover")

        result = ctrl.run("msg", "banzai")

        state = store.load()
        assert result.status == "blocked"
        assert state["blocked_reason"] == "agent_blocked"
        assert state["recovery_instruction"] == {
            "schema_version": 1,
            "kind": "retry_phase",
            "reason_code": "agent_blocked",
            "phase": "phase1-discover",
            "requires_human_input": False,
        }
        assert "blocked_decision" not in state

    def test_sigint_handler_defers_state_store_io(self, tmp_path):
        ctrl, store = _controller(tmp_path)

        with patch.object(store, "set_cancel_requested") as persist_cancel:
            ctrl._handle_sigint(None, None)

        assert ctrl._cancelled is True
        persist_cancel.assert_not_called()

    def test_stale_cancel_requested_cleared_on_resume(self, tmp_path):
        """cancel_requested left in state.json by a previous Ctrl+C does not
        prevent a fresh echelon run invocation from proceeding."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "init")
        store.set_cancel_requested()   # simulate previous run's Ctrl+C
        # run() must clear it and proceed normally (not exit immediately)
        result = ctrl.run("msg", "banzai")
        assert result.status != "interrupted"

    def test_budget_zero_never_exhausts(self, tmp_path):
        """token_budget=0 means disabled — should not trigger budget_exhausted."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "DONE")
        result = ctrl.run("msg", "banzai")
        assert result.status != "budget_exhausted"

    def test_budget_exhausted_when_exceeded(self, tmp_path):
        provider = _mock_provider()
        graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
        store = SquadStateStore(tmp_path / "squad" / "run-test")
        ctrl = SquadController(
            provider=provider,
            state_store=store,
            phase_graph=graph,
            ext_dir=EXT_ROOT / "runtime",
            project_root=tmp_path,
            token_budget=100,   # very low
        )
        store.initialize("r", "banzai", "msg", 100, "init")
        store.increment_token_usage(100)  # exhaust immediately
        result = ctrl.run("msg", "banzai")
        assert result.status == "budget_exhausted"

    def test_unknown_phase_type_calls_judgment(self, tmp_path):
        """Unknown type → judgment_dispatch → provider.exec_agent called."""
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider)

        # Inject a fake phase with unknown type and a simple 'always' transition to DONE
        fake = PhaseNode(
            id="fake-unknown",
            type="unknown_type",
            transitions=[{"to": "DONE", "condition": "always"}],
        )
        ctrl._graph._phases["fake-unknown"] = fake
        store.initialize("r", "banzai", "msg", 0, "fake-unknown")
        result = ctrl.run("msg", "banzai")
        # Provider must have been called (COMMANDER judgment)
        assert provider.exec_agent.called

    def test_iterative_phase3_consensus_uses_max_iterations_not_generic_cap(
        self,
        tmp_path,
        monkeypatch,
    ):
        """phase3-consensus can legitimately repeat up to max_iterations."""
        _disable_lexicon_gate(tmp_path)
        provider = _mock_provider("PASS")
        default_result = provider.exec_agent.return_value

        def consensus_result(project_root: str, prompt: str, *args, **kwargs):
            if "Operate in **PLAN2** mode" in prompt:
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={"verdict": "COMPLETE", "state_updates": {}},
                    raw_output="",
                    duration_ms=100,
                    timed_out=False,
                )
            return default_result

        provider.exec_agent.side_effect = consensus_result
        ctrl, store = _controller(tmp_path, provider, mode="semi")
        store.initialize("r", "semi", "msg", 0, "phase3-consensus", max_iterations=10)
        state = store.load()
        state["iteration"] = 4
        state["phase_dispatch_counts"] = {"phase3-consensus": 5}
        store.save(state)
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        _write_phase_a_build_inputs(spec_dir)
        (spec_dir / "implementability-report.md").write_text(
            "# implementability-report.md\n",
            encoding="utf-8",
        )
        state = store.load()
        state["spec_id"] = "001-demo"
        state["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(state)
        _install_passing_understanding(monkeypatch)

        result = ctrl.run("msg", "semi")

        assert provider.exec_agent.called
        assert result.status == "done"
        assert store.load().get("blocked_reason") != "phase_dispatch_limit"

    def test_why_fail_increments_on_fail(self, tmp_path):
        """why_fail_count increments when a WHY phase returns quality_gates.fail."""
        from harness.squad_provider import SquadAgentResult
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {"quality_scores": [{"pass": False}]},
            },
            raw_output="", duration_ms=0, timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-why1", max_iterations=5)
        ctrl.run("msg", "banzai")
        # why_fail_count should have been incremented (≥1)
        assert store.load().get("why_fail_count", 0) >= 1

    def test_sage_quality_scores_are_quarantined_and_cannot_override_certified_failure(self, tmp_path):
        """WHY2 model output cannot replace controller-certified score history."""
        from harness.squad_provider import SquadAgentResult
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {
                    "quality_scores": [{
                        "pass": "WHY2-iter-0",
                        "overall": 0.745,
                        "structure": 0.660,
                        "testability": 0.679,
                    }],
                    "evidence_resolution_status": "not_required",
                    "finding_routes": {
                        "findings": [{
                            "issue_id": "ISS-QUALITY",
                            "route": "spec_repair",
                            "rationale": "The qualitative review failed.",
                        }]
                    },
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize(
            "r",
            "banzai",
            "msg",
            0,
            "phase1-why2",
            max_iterations=5,
            spec_authoring_mode="perfectionist",
        )
        _mark_constitution_complete(tmp_path, store)
        state = store.load()
        state["quality_scores"] = [
            {
                "pass": False,
                "pass_id": "WHY2-iter-0",
                "source": "harness:understanding",
            }
        ]
        store.save(state)

        node = ctrl._graph.get("phase1-why2")
        result = ctrl._executors["agent"]._validate_result_state_updates(
            node,
            provider.exec_agent.return_value,
            result_contract=node.result_contract(),
        )
        assert result.state_updates == {
            "evidence_resolution_status": "not_required",
            "finding_routes": {
                "findings": [{
                    "issue_id": "ISS-QUALITY",
                    "route": "spec_repair",
                    "rationale": "The qualitative review failed.",
                }]
            },
        }
        assert "quality_scores" in result.quarantined_state_updates
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(node, result, snapshot)
        decision = ctrl._coordinate_transition_routing(
            node,
            prepared,
            snapshot,
        )
        store.advance(
            "phase1-why2",
            decision.to_phase,
            decision,
        )

        state = store.load()
        assert state["phase"] == "phase1-what"
        assert state["quality_scores"][-1]["pass"] is False
        assert state["quality_scores"][-1]["pass_id"] == "WHY2-iter-0"
        assert state["quality_scores"][-1]["source"] == "harness:understanding"
        assert state.get("why_fail_count", 0) >= 1

    def test_sage_qualitative_failure_overrides_certified_pass(self, tmp_path):
        """WHY2 may make a certified pass stricter without replacing its score."""
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "banzai",
            "msg",
            0,
            "phase1-why2",
            max_iterations=5,
            spec_authoring_mode="perfectionist",
        )
        state = store.load()
        state["quality_scores"] = [
            {
                "pass": True,
                "pass_id": "WHY2-iter-0",
                "source": "harness:understanding",
            }
        ]
        store.save(state)
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {
                    "evidence_resolution_status": "not_required",
                    "finding_routes": {
                        "findings": [{
                            "issue_id": "ISS-QUALITY",
                            "route": "spec_repair",
                            "rationale": "The qualitative review failed.",
                        }]
                    },
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        next_phase = _coordinate_prepared_result(ctrl,
            ctrl._graph.get("phase1-why2"),
            result,
        )

        assert next_phase == "phase1-what"
        assert store.load()["quality_scores"][-1]["pass"] is True
        assert store.load().get("why_fail_count", 0) == 1

    def test_understanding_operational_failure_remains_at_retryable_gate(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-understanding")
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "BLOCKED",
                "state_updates": {
                    "blocked_reason": "Understanding analysis failed: temporary",
                    "understanding_evidence": {
                        "phase": "phase1-why2",
                        "status": "error",
                        "path": "/tmp/understanding-error.json",
                    },
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        snapshot = store.capture_routing_snapshot(
            expected_phase="phase1-understanding"
        )
        ctrl._block_after_executor_failure(
            "phase1-understanding",
            "Understanding analysis failed: temporary",
            result,
            snapshot=snapshot,
        )

        blocked = store.load()
        assert blocked["status"] == "blocked"
        assert blocked["phase"] == "phase1-understanding"
        assert blocked["understanding_evidence"]["status"] == "error"

    def test_blocked_understanding_gate_retries_without_reinitializing(self, tmp_path):
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-understanding")
        state = store.load()
        state.update(
            {
                "status": "blocked",
                "blocked_reason": "Understanding analysis failed: temporary",
                "understanding_evidence": {
                    "phase": "phase1-why2",
                    "status": "error",
                    "path": "/tmp/original-evidence.json",
                },
            }
        )
        store.save(state)
        _mark_constitution_complete(tmp_path, store)
        retry = MagicMock()
        retry.execute.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "BLOCKED",
                "state_updates": {"blocked_reason": "retry failed"},
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl._executors["deterministic_understanding"] = retry

        with patch.object(ctrl._graph, "entry_phase", return_value="DONE"):
            resumed = ctrl.run("msg", "banzai")

        assert retry.execute.call_count == 1
        assert resumed.status == "blocked"
        assert store.load()["phase"] == "phase1-understanding"
        assert store.load()["understanding_evidence"]["path"] == "/tmp/original-evidence.json"

    def test_why_fail_resets_on_pass(self, tmp_path):
        """why_fail_count resets when a WHY phase passes."""
        from harness.squad_provider import SquadAgentResult
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": {"quality_scores": [{"pass": True}]},
            },
            raw_output="", duration_ms=0, timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-why1", max_iterations=5)
        store.increment_why_fail_count()
        store.increment_why_fail_count()
        ctrl.run("msg", "banzai")
        assert store.load().get("why_fail_count", 0) == 0

    def test_consecutive_why1_fails_remain_in_the_declared_discovery_loop(self, tmp_path):
        """WHY1 has no spec issue ledger, so its graph iteration cap owns retries."""
        from harness.squad_provider import SquadAgentResult
        provider = _mock_provider()
        why1_result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {"quality_scores": [{"pass": False}]},
            },
            raw_output="", duration_ms=0, timed_out=False,
        )
        provider.exec_agent.return_value = why1_result
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "semi", "msg", 0, "phase1-why1", max_iterations=5)
        # Pre-set why_fail_count=1 so next fail triggers guard
        store.increment_why_fail_count()
        # Set last_dispatch.completed_at to a past timestamp so
        # _staging_changed_since does not return True (no staging .md files)
        state = store.load()
        state["last_dispatch"] = {"completed_at": "2020-01-01T00:00:00Z"}
        store.save(state)

        next_phase = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why1"),
            why1_result,
        )

        assert next_phase == "phase1-discover"
        state = store.load()
        assert state.get("escalation_question") is None

    def test_consecutive_why2_fail_with_active_spec_progress_routes_to_repair(self, tmp_path):
        """Fresh WHY2 artifacts in state.spec_dir count as progress."""
        provider = _mock_provider()
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {
                    "evidence_resolution_status": "not_required",
                    "finding_routes": {
                        "findings": [{
                            "issue_id": "ISS-PROGRESS",
                            "route": "spec_repair",
                            "rationale": "The active specification needs repair.",
                        }]
                    },
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize(
            "r", "semi", "msg", 0, "phase1-why2", max_iterations=5,
            spec_authoring_mode="perfectionist",
        )
        store.increment_why_fail_count()

        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "issues.md").write_text("# Fresh WHY2 findings\n", encoding="utf-8")
        state = store.load()
        state["spec_dir"] = "runs/run-test/specs/001-demo"
        state["last_dispatch"] = {"completed_at": "2020-01-01T00:00:00Z"}
        store.save(state)

        node = ctrl._graph.get("phase1-why2")
        next_phase = _coordinate_prepared_result(ctrl, node, result)

        assert next_phase == "phase1-what"
        assert store.load().get("escalation_question") is None

    def test_what_artifact_repair_starts_a_fresh_why_failure_cycle(self, tmp_path):
        """A repaired spec must not inherit a WHY failure from its prior version."""
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r", "semi", "msg", 0, "phase1-what", max_iterations=5,
            spec_authoring_mode="perfectionist",
        )
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Repaired specification\n", encoding="utf-8")
        state = store.load()
        state.update(
            {
                "spec_dir": "runs/run-test/specs/001-demo",
                "why_fail_count": 1,
                "why2_metric_stagnation_count": 1,
                "why_failure_baseline": {
                    "phase_id": "phase1-why2",
                    "recorded_at": "2020-01-01T00:00:00+00:00",
                },
            }
        )
        store.save(state)

        what_result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": {"evidence_resolution_status": "not_required"},
            },
            raw_output="", duration_ms=0, timed_out=False,
        )
        _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-what"),
            what_result,
        )

        refreshed = store.load()
        assert refreshed["why_fail_count"] == 0
        assert refreshed["why2_metric_stagnation_count"] == 0

        why2_result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {
                    "evidence_resolution_status": "not_required",
                    "finding_routes": {
                        "findings": [{
                            "issue_id": "ISS-FRESH",
                            "route": "spec_repair",
                            "rationale": "The active specification needs repair.",
                        }]
                    },
                },
            },
            raw_output="", duration_ms=0, timed_out=False,
        )
        store.save({**store.load(), "phase": "phase1-why2"})
        assert (
            _coordinate_prepared_result(
                ctrl,
                ctrl._graph.get("phase1-why2"),
                why2_result,
            )
            == "phase1-what"
        )
        assert store.load()["why_fail_count"] == 1
        assert store.load().get("escalation_question") is None

    def test_selected_issue_repair_consumes_recovery_after_what_changes_spec(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "phase1-what", max_iterations=5)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Repaired specification\n", encoding="utf-8")
        state = store.load()
        state.update(
            {
                "spec_dir": "runs/run-test/specs/001-demo",
                "selected_issue_resolution": "ISS-001",
                "issue_resolution_ledger": {
                    "ISS-001": {"issue_id": "ISS-001", "status": "selected"},
                    "ISS-002": {"issue_id": "ISS-002", "status": "pending"},
                },
                "issue_resolution_repair_baseline": {
                    "issue_id": "ISS-001",
                    "repair_phase": "phase1-what",
                    "recorded_at": "2020-01-01T00:00:00+00:00",
                },
                "issue_resolution_recovery": {"issue_id": "ISS-001"},
            }
        )
        store.save(state)

        _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-what"),
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {"evidence_resolution_status": "not_required"},
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            ),
        )

        refreshed = store.load()
        assert refreshed["issue_resolution_ledger"]["ISS-001"]["status"] == "repaired"
        assert refreshed["issue_resolution_ledger"]["ISS-002"]["status"] == "pending"
        assert refreshed["issue_resolution_recovery"]["status"] == "consumed"

    def test_quality_remediation_rejects_done_without_spec_change(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "phase1-what", max_iterations=5)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        spec = spec_dir / "spec.md"
        spec.write_text("# Specification\n", encoding="utf-8")
        state = store.load()
        state.update(
            {
                "spec_dir": "runs/run-test/specs/001-demo",
                "quality_gate_remediation": {
                    "baseline_spec_sha256": hashlib.sha256(
                        spec.read_bytes()
                    ).hexdigest(),
                },
            }
        )
        store.save(state)

        next_phase = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-what"),
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {
                        "evidence_resolution_status": "not_required",
                    },
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            ),
        )

        assert next_phase == "terminal-blocked"
        refreshed = store.load()
        assert refreshed["blocked_reason"] == (
            "quality_gate_remediation_no_artifact_progress"
        )

    def test_selected_issue_repair_accepts_an_already_present_spec_amendment(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "phase1-what", max_iterations=5)
        state = store.load()
        state.update(
            {
                "selected_issue_resolution": "ISS-001",
                "issue_resolution_ledger": {
                    "ISS-001": {"issue_id": "ISS-001", "status": "selected"},
                },
                "issue_resolution_repair_baseline": {
                    "issue_id": "ISS-001",
                    "repair_phase": "phase1-what",
                    "recorded_at": "2099-01-01T00:00:00+00:00",
                },
                "issue_resolution_recovery": {"issue_id": "ISS-001"},
            }
        )
        store.save(state)

        _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-what"),
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {"evidence_resolution_status": "not_required"},
                },
                raw_output="", duration_ms=0, timed_out=False,
            ),
        )

        refreshed = store.load()
        assert refreshed["issue_resolution_ledger"]["ISS-001"]["status"] == "repaired"
        assert refreshed["issue_resolution_recovery"]["status"] == "consumed"

    def test_selected_phase3_issue_is_repaired_by_its_sealed_owner(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "phase3-sentinel", max_iterations=5)
        state = store.load()
        state.update(
            {
                "selected_issue_resolution": "ISS-001",
                "issue_resolution_ledger": {
                    "ISS-001": {
                        "issue_id": "ISS-001",
                        "status": "selected",
                        "repair_phase": "phase3-sentinel",
                    },
                },
                "issue_resolution_repair_baseline": {
                    "issue_id": "ISS-001",
                    "repair_phase": "phase3-sentinel",
                    "recorded_at": "2026-08-24T00:00:00+00:00",
                },
                "issue_resolution_recovery": {"issue_id": "ISS-001"},
            }
        )
        store.save(state)

        _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase3-sentinel"),
            SquadAgentResult(
                exit_code=0,
                echelon_result={"verdict": "DONE", "state_updates": {}},
                raw_output="",
                duration_ms=0,
                timed_out=False,
            ),
        )

        refreshed = store.load()
        assert refreshed["issue_resolution_ledger"]["ISS-001"]["status"] == (
            "repaired"
        )
        assert refreshed["issue_resolution_recovery"]["status"] == "consumed"

    def test_passing_why3_validates_repaired_phase3_issue(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "phase3-consensus", max_iterations=5)
        state = store.load()
        state.update(
            {
                "why3_verdict": "PASS",
                "assess2_verdict": "PASS",
                "gate_decision": "PASS",
                "selected_issue_resolution": "ISS-001",
                "issue_resolution_ledger": {
                    "ISS-001": {
                        "issue_id": "ISS-001",
                        "status": "repaired",
                        "repair_phase": "phase3-sentinel",
                    },
                },
                "issue_resolution_repair_baseline": {
                    "issue_id": "ISS-001",
                    "repair_phase": "phase3-sentinel",
                    "recorded_at": "2026-08-24T00:00:00+00:00",
                },
                "issue_resolution_recovery": {
                    "issue_id": "ISS-001",
                    "status": "consumed",
                },
            }
        )
        store.save(state)

        _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase3-consensus"),
            SquadAgentResult(
                exit_code=0,
                echelon_result={"verdict": "PASS", "state_updates": {}},
                raw_output="",
                duration_ms=0,
                timed_out=False,
            ),
        )

        refreshed = store.load()
        assert refreshed["issue_resolution_ledger"]["ISS-001"]["status"] == (
            "validated"
        )
        assert refreshed["selected_issue_resolution"] is None
        assert refreshed["issue_resolution_repair_baseline"] is None
        assert refreshed["issue_resolution_recovery"]["status"] == "validated"

    def test_passing_why2_validates_only_the_repaired_selected_issue(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r", "semi", "msg", 0, "phase1-why2", max_iterations=5,
            spec_authoring_mode="perfectionist",
        )
        state = store.load()
        state.update(
            {
                "selected_issue_resolution": "ISS-001",
                "issue_resolution_ledger": {
                    "ISS-001": {"issue_id": "ISS-001", "status": "repaired"},
                    "ISS-002": {"issue_id": "ISS-002", "status": "pending"},
                },
            }
        )
        store.save(state)
        node = ctrl._graph.get("phase1-why2")
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(
            node,
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "PASS",
                    "state_updates": {
                        "evidence_resolution_status": "not_required",
                        "finding_routes": {"findings": []},
                    },
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            ),
            snapshot,
        )

        override, updates, request = ctrl._coordinate_why_transition_state(
            node,
            prepared,
            snapshot,
        )

        assert override is None
        assert request is None
        assert updates["issue_resolution_ledger"]["ISS-001"]["status"] == "validated"
        assert updates["issue_resolution_ledger"]["ISS-002"]["status"] == "pending"
        assert updates["selected_issue_resolution"] is None

    def test_failing_why2_validates_repaired_issue_absent_from_remaining_findings(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r", "semi", "msg", 0, "phase1-why2", max_iterations=5,
            spec_authoring_mode="perfectionist",
        )
        state = store.load()
        state.update(
            {
                "selected_issue_resolution": "ISS-001",
                "issue_resolution_ledger": {
                    "ISS-001": {"issue_id": "ISS-001", "status": "repaired"},
                    "ISS-002": {"issue_id": "ISS-002", "status": "pending"},
                },
            }
        )
        store.save(state)
        node = ctrl._graph.get("phase1-why2")
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(
            node,
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "FAIL",
                    "state_updates": {
                        "evidence_resolution_status": "not_required",
                        "finding_routes": {"findings": [{
                            "issue_id": "ISS-002",
                            "route": "spec_repair",
                            "rationale": "A separate repair is still required.",
                        }]},
                    },
                },
                raw_output="", duration_ms=0, timed_out=False,
            ),
            snapshot,
        )

        override, updates, human_input = ctrl._coordinate_why_transition_state(
            node, prepared, snapshot
        )

        assert override == "terminal-blocked"
        assert human_input is None
        assert updates["blocked_reason"] == "issue_resolution_next"
        assert updates["issue_resolution_ledger"]["ISS-001"]["status"] == "validated"
        assert updates["selected_issue_resolution"] is None

    def test_failing_why2_does_not_reopen_a_repaired_selected_issue(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r", "semi", "msg", 0, "phase1-why2", max_iterations=5,
            spec_authoring_mode="perfectionist",
        )
        state = store.load()
        state.update({
            "selected_issue_resolution": "ISS-001",
            "issue_resolution_ledger": {
                "ISS-001": {"status": "repaired"},
            },
        })
        store.save(state)
        node = ctrl._graph.get("phase1-why2")
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(
            node,
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "FAIL",
                    "state_updates": {
                        "evidence_resolution_status": "not_required",
                        "finding_routes": {"findings": [{
                            "issue_id": "ISS-001",
                            "route": "spec_repair",
                            "rationale": "A stale report repeats the selected issue.",
                        }]},
                    },
                },
                raw_output="", duration_ms=0, timed_out=False,
            ),
            snapshot,
        )

        next_phase, state_updates, human_input = ctrl._coordinate_why_transition_state(
            node, prepared, snapshot
        )

        assert next_phase == "phase1-what"
        assert human_input is None
        assert state_updates["iteration"] == 0
        assert "quality_gate_remediation" in state_updates
        assert state_updates["issue_resolution_ledger"]["ISS-001"]["status"] == "validated"
        assert state_updates["selected_issue_resolution"] is None

    def test_failing_why2_starts_quality_remediation_after_last_resolution(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r", "semi", "msg", 0, "phase1-why2", max_iterations=5,
            spec_authoring_mode="perfectionist",
        )
        state = store.load()
        state.update(
            {
                "selected_issue_resolution": "ISS-001",
                "issue_resolution_ledger": {
                    "ISS-001": {"status": "repaired"},
                    "ISS-002": {"status": "validated"},
                },
            }
        )
        store.save(state)
        node = ctrl._graph.get("phase1-why2")
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(
            node,
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "FAIL",
                    "state_updates": {
                        "evidence_resolution_status": "not_required",
                        "finding_routes": {"findings": [{
                            "issue_id": "ISS-001",
                            "route": "spec_repair",
                            "rationale": "Stale issue report.",
                        }]},
                    },
                },
                raw_output="", duration_ms=0, timed_out=False,
            ),
            snapshot,
        )

        next_phase, updates, human_input = ctrl._coordinate_why_transition_state(
            node, prepared, snapshot
        )

        assert next_phase == "phase1-what"
        assert human_input is None
        assert updates["iteration"] == 0
        assert updates["quality_gate_remediation"]["evidence"] is None

    def test_failing_why2_with_all_validated_issues_uses_current_quality_remediation(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r", "semi", "msg", 0, "phase1-why2", max_iterations=5,
            spec_authoring_mode="perfectionist",
        )
        state = store.load()
        state.update(
            {
                "issue_resolution_ledger": {
                    "ISS-006": {"status": "validated"},
                    "ISS-007": {"status": "validated"},
                },
                "understanding_evidence": {
                    "phase": "phase1-why2",
                    "status": "completed",
                    "path": "evidence/current.json",
                },
                "why_fail_count": 1,
                "why2_metric_stagnation_count": 1,
            }
        )
        store.save(state)
        node = ctrl._graph.get("phase1-why2")
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(
            node,
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "FAIL",
                    "state_updates": {
                        "evidence_resolution_status": "not_required",
                        "finding_routes": {"findings": [{
                            "issue_id": "ISS-006",
                            "route": "spec_repair",
                            "rationale": "Historical stale finding.",
                        }]},
                    },
                },
                raw_output="", duration_ms=0, timed_out=False,
            ),
            snapshot,
        )

        next_phase, updates, human_input = ctrl._coordinate_why_transition_state(
            node, prepared, snapshot
        )

        assert next_phase == "phase1-what"
        assert human_input is None
        assert updates["why_fail_count"] == 0
        assert updates["why2_metric_stagnation_count"] == 0
        assert updates["quality_gate_remediation"]["evidence"] == state[
            "understanding_evidence"
        ]

    def test_failing_why2_carries_qualitative_findings_into_quality_remediation(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r", "semi", "msg", 0, "phase1-why2", max_iterations=5,
            spec_authoring_mode="perfectionist",
        )
        state = store.load()
        state.update(
            {
                "issue_resolution_ledger": {
                    "ISS-001": {"status": "validated"},
                },
                "understanding_evidence": {
                    "phase": "phase1-why2",
                    "status": "completed",
                    "path": "evidence/current.json",
                    "pass": True,
                    "failing_gates": [],
                },
            }
        )
        store.save(state)
        node = ctrl._graph.get("phase1-why2")
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        qualitative_findings = [
            {
                "issue_id": "ISS-001",
                "route": "spec_repair",
                "rationale": "FR-033 contradicts FR-034.",
            },
            {
                "issue_id": "ISS-002",
                "route": "spec_repair",
                "rationale": "AC-037 contradicts FR-038.",
            },
        ]
        prepared = ctrl._prepare_phase_result(
            node,
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "FAIL",
                    "state_updates": {
                        "evidence_resolution_status": "not_required",
                        "finding_routes": {"findings": qualitative_findings},
                    },
                },
                raw_output="", duration_ms=0, timed_out=False,
            ),
            snapshot,
        )

        next_phase, updates, human_input = ctrl._coordinate_why_transition_state(
            node, prepared, snapshot
        )

        assert next_phase == "phase1-what"
        assert human_input is None
        remediation = updates["quality_gate_remediation"]
        assert remediation["evidence"] == state["understanding_evidence"]
        assert remediation["qualitative_findings"] == qualitative_findings

    def test_consecutive_why_escalation_gives_an_actionable_question(self, tmp_path):
        from echelon.cli import _classify_run_recovery

        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r", "semi", "msg", 0, "phase1-why2", max_iterations=5,
            spec_authoring_mode="perfectionist",
        )
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "issues.md").write_text("# Findings\n", encoding="utf-8")
        state = store.load()
        state.update(
            {
                "spec_dir": "runs/run-test/specs/001-demo",
                "why_fail_count": 1,
                "why_failure_baseline": {
                    "phase_id": "phase1-why2",
                    "recorded_at": "2999-01-01T00:00:00+00:00",
                },
            }
        )
        store.save(state)
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "FAIL",
                "state_updates": {
                    "evidence_resolution_status": "not_required",
                    "finding_routes": {
                        "findings": [{
                            "issue_id": "ISS-BLOCKED",
                            "route": "spec_repair",
                            "rationale": "The active specification needs repair.",
                        }]
                    },
                },
            },
            raw_output="", duration_ms=0, timed_out=False,
        )

        assert (
            _coordinate_prepared_result(
                ctrl,
                ctrl._graph.get("phase1-why2"),
                result,
            )
            == "terminal-blocked"
        )
        awaiting = store.load()
        question = awaiting["escalation_question"]
        assert 'echelon spec resume "<your answer>"' in question
        assert "resets the consecutive WHY failure count" in question
        assert "reopens phase1-why2" in question
        assert "echelon spec resolve" not in question
        action = _classify_run_recovery(awaiting, project_root=tmp_path)
        assert action.kind == "human_resume"
        assert action.command == 'echelon spec resume "<your answer>"'

        answer = "Narrow the scope to the public API and retry its repair."
        assert ctrl.resume_with_human_input(answer)
        resumed = store.load()
        assert resumed["status"] == "running"
        assert resumed["phase"] == "phase1-why2"
        assert resumed["why_fail_count"] == 0
        assert resumed["blocked_decision"]["status"] == "resolved"
        assert resumed["blocked_decision"]["answer_text"] == answer
        assert "recovery_instruction" not in resumed

    def test_banzai_free_text_escalation_awaits_human(self, tmp_path, monkeypatch):
        """Banzai free text without a recommendation remains human-only."""
        from harness.squad_provider import SquadAgentResult
        _disable_lexicon_gate(tmp_path)
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "STOP_AND_ASK",
                "state_updates": {
                    "quality_scores": [],
                    "status": "blocked",
                    "escalation_question": "Q1: Do you own the IP?",
                    "blocked_reason": "human_clarification_required",
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        monkeypatch.setattr(
            ctrl,
            "_lexicon_gate_config",
            lambda: {"lexicon_gate": {"enabled": False, "spec_enabled": False}},
        )
        store.initialize(
            "r", "banzai", "msg", 0, "phase1-why1", max_iterations=5,
            spec_authoring_mode="perfectionist",
        )
        _mark_constitution_complete(tmp_path, store)
        result = ctrl.run("msg", "banzai")

        assert provider.exec_agent.call_count == 1
        assert result.status == "blocked"
        final_state = store.load()
        assert final_state["blocked_decision"]["schema_version"] == 3
        assert final_state["blocked_decision"]["status"] == "awaiting_human"
        assert final_state["blocked_decision"]["automatic_eligible"] is False
        assert final_state["recovery_instruction"]["kind"] == (
            "await_human_answer"
        )

    def test_semi_escalation_inline_when_agent_sets_escalation_question(self, tmp_path):
        """Semi: WHY1 returns escalation_question in state_updates → run stops blocked."""
        from harness.squad_provider import SquadAgentResult
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "STOP_AND_ASK",
                "state_updates": {
                    "quality_scores": [],
                    "status": "blocked",
                    "escalation_question": "Q1: Do you own the IP?",
                    "blocked_reason": "human_clarification_required",
                },
            },
            raw_output="", duration_ms=0, timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        _install_test_clarification_policy(
            ctrl,
            source_kind="provider_escalation",
            producer_id="phase1-why1",
            phase_id="phase1-why1",
        )
        store.initialize("r", "semi", "msg", 0, "phase1-why1", max_iterations=5)
        result = ctrl.run("msg", "semi")
        assert result.status == "blocked"
        state = store.load()
        assert state["blocked_decision"]["status"] == "awaiting_human"
        assert state["blocked_decision"]["question"] == "Q1: Do you own the IP?"
        assert state["escalation_question"] == "Q1: Do you own the IP?"

    def test_phase1_tracker_stop_and_ask_blocks_with_resume_question(self, tmp_path):
        """TRACKER STOP_AND_ASK must produce a resumable blocked run."""
        from harness.squad_provider import SquadAgentResult
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "STOP_AND_ASK",
                "state_updates": {
                    "status": "blocked",
                    "blocked_reason": "phase1-tracker: user intent needs clarification",
                    "escalation_question": "Should Echelon target Opta Stark, MSA, or both?",
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        _install_test_clarification_policy(
            ctrl,
            source_kind="provider_escalation",
            producer_id="phase1-tracker",
            phase_id="phase1-tracker",
            reason_code=(
                "phase1-tracker: user intent needs clarification"
            ),
        )
        store.initialize("r", "semi", "msg", 0, "phase1-tracker", max_iterations=5)

        result = ctrl.run("msg", "semi")
        state = store.load()

        assert result.status == "blocked"
        assert state["phase"] == "phase1-tracker"
        assert state["blocked_reason"] == "phase1-tracker: user intent needs clarification"
        assert state["escalation_question"] == "Should Echelon target Opta Stark, MSA, or both?"
        assert state["blocked_decision"]["status"] == "awaiting_human"

    def test_fresh_checkpoint_question_ignores_stale_escalation_resolved(self, tmp_path):
        """A prior resume must not suppress a later checkpoint human-gate question."""
        _disable_lexicon_gate(tmp_path)
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider, mode="semi")
        policy = _install_test_clarification_policy(
            ctrl,
            source_kind="legacy_recovery",
            producer_id="checkpoint-assess",
            phase_id="checkpoint-assess",
        )
        store.initialize("r", "semi", "msg", 0, "checkpoint-assess", max_iterations=5)
        _mark_constitution_complete(tmp_path, store)
        state = store.load()
        state["escalation_resolved"] = True
        store.save(state)
        request = HumanInputPolicyRegistry((policy,)).prepare(
            source_kind=policy.source_kind,
            producer_id=policy.producer_id,
            phase_id="checkpoint-assess",
            reason_code=policy.reason_code,
            question="Approve the Phase 1 gate?",
            source_state_revision=store.load()["state_revision"],
        )

        assert ctrl.handle_human_input(request) is False
        state = store.load()

        provider.exec_agent.assert_not_called()
        assert state["blocked_reason"] == "human_clarification_required"
        assert state["escalation_question"] == "Approve the Phase 1 gate?"
        assert state["blocked_decision"]["status"] == "awaiting_human"
        assert state["escalation_resolved"] is False
        assert state.get("blocked_reason") != "phase_dispatch_limit"

    def test_banzai_human_only_decision_does_not_dispatch_commander(self, tmp_path):
        """A sealed human-only Banzai decision remains awaiting the user."""
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        policy = _install_test_clarification_policy(
            ctrl,
            source_kind="legacy_recovery",
            producer_id="legacy-ip-question",
            phase_id="phase1-investigate",
        )
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-investigate",
            max_iterations=5,
            autonomy_mode="banzai",
        )
        request = HumanInputPolicyRegistry((policy,)).prepare(
            source_kind=policy.source_kind,
            producer_id=policy.producer_id,
            phase_id="phase1-investigate",
            reason_code=policy.reason_code,
            question="Q1: Do you have author rights?",
            source_state_revision=store.load()["state_revision"],
        )
        store.set_human_input_decision(
            request,
            initial_status="awaiting_human",
        )

        assert ctrl.resume_pending_human_input() is False
        state = store.load()
        assert state["status"] == "blocked"
        assert state["phase"] == "phase1-investigate"
        assert state["blocked_decision"]["status"] == "awaiting_human"
        assert state["blocked_decision"]["automatic_eligible"] is False
        assert state["blocked_decision"]["resolved_by"] is None
        provider.exec_agent.assert_not_called()

    def test_semi_escalation_stops_run(self, tmp_path):
        """Semi mode: blocked+escalation_question → run stops with status=blocked."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "semi", "msg", 0, "DONE", max_iterations=5)
        state = store.load()
        state["status"] = "blocked"
        state["escalation_question"] = "Q1: Do you have author rights?"
        state["blocked_reason"] = "WHY1: user-gated issues"
        state["mode"] = "semi"
        store.save(state)
        result = ctrl.run("msg", "semi")
        assert result.status == "blocked"

    def test_guided_escalation_stops_run(self, tmp_path):
        """Guided mode: blocked+escalation_question → run stops with status=blocked."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "guided", "msg", 0, "DONE", max_iterations=5)
        state = store.load()
        state["status"] = "blocked"
        state["escalation_question"] = "Q1: Do you have author rights?"
        state["mode"] = "guided"
        store.save(state)
        result = ctrl.run("msg", "guided")
        assert result.status == "blocked"


def _proportional_assessment_fixture(
    ctrl: SquadController,
    store: SquadStateStore,
    assessment_index: int,
    *,
    score: float = 0.60,
    spec_text: str | None = None,
    overview_text: str | None = None,
    requirement_count: int = 1,
) -> tuple[dict[str, object], SquadAgentResult]:
    """Materialize one immutable failing Understanding/SAGE assessment."""
    spec_dir = ctrl._project_root / "runs" / "run-test" / "specs" / "001-demo"
    spec_dir.mkdir(parents=True, exist_ok=True)
    content = spec_text or (
        f"# Candidate {assessment_index}\n\n"
        f"- FR-001: The system shall render candidate {assessment_index}.\n"
    )
    issues = f"""# Issues — WHY2

## Summary
- **CRITICAL:** 0
- **HIGH:** 0
- **MEDIUM:** 0
- **LOW:** 1
- **Verdict:** FAIL

## Issues

### ISS-QUALITY-{assessment_index}: Residual quality debt
- **Severity:** LOW
- **Type:** incompleteness
- **Description:** The certified overall gate remains below threshold.
- **Affected artifact:** spec.md
- **Affected section:** Requirements
- **Evidence:** The immutable Understanding score is below threshold.
- **Recommendation:** Repair the failing quality dimension.
- **Responsible agent:** WHAT
- **Action Required:** Amend the specification.

### Resolution Guidance
- **Decision required:** No user decision — agent repair
- **Suggested option:** Repair the certified failing dimension.
- **Evidence basis:** Immutable Understanding evidence.
- **Values not inferable:** None
- **Banzai eligible:** no

## Pre-Mortem Findings

| Risk | Likelihood | Impact | Affected Requirements |
|------|-----------|--------|----------------------|

## Cross-Artifact Consistency

| Check | Status | Notes |
|-------|--------|-------|
"""
    for name, artifact in {
        "spec.md": content,
        "requirements-overview.md": (
            overview_text
            if overview_text is not None
            else f"# Overview {assessment_index}\n"
        ),
        "quality-gates.md": f"# Quality gates {assessment_index}\n",
        "issues.md": issues,
    }.items():
        (spec_dir / name).write_text(artifact, encoding="utf-8")

    report = {
        "schema_version": 1,
        "status": "completed",
        "phase": "phase1-why2",
        "iteration": assessment_index,
        "spec": {
            "path": "runs/run-test/specs/001-demo/spec.md",
            "sha256": hashlib.sha256(
                (spec_dir / "spec.md").read_bytes()
            ).hexdigest(),
        },
        "thresholds": {"overall": 0.80},
        "scores": {"overall": score},
        "gates": {
            "overall": {
                "score": score,
                "threshold": 0.80,
                "pass": False,
                "numeric_pass": False,
                "pass_basis": "numeric_threshold",
            },
        },
        "pass": False,
        "requirement_count": requirement_count,
    }
    report_path = (
        ctrl._squad_dir
        / "evidence"
        / "understanding"
        / f"phase1-why2-iter-{assessment_index}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
    evidence = {
        "phase": "phase1-why2",
        "iteration": assessment_index,
        "status": "completed",
        "path": str(report_path),
        "digest": report_digest,
        "pass": False,
        "failing_gates": ["overall"],
        "error": None,
    }
    score_history = list(store.load().get("quality_scores") or [])
    score_history.append(
        {
            "pass": False,
            "pass_id": f"WHY2-iter-{assessment_index}",
            "source": "harness:understanding",
            "evidence": str(report_path),
            "evidence_digest": report_digest,
            "overall": score,
        }
    )
    why2_result = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "FAIL",
            "state_updates": {
                "evidence_resolution_status": "not_required",
                "finding_routes": {
                    "findings": [
                        {
                            "issue_id": f"ISS-QUALITY-{assessment_index}",
                            "route": "spec_repair",
                            "rationale": "The certified overall gate remains below threshold.",
                        }
                    ]
                },
            },
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    return {
        "understanding_evidence": evidence,
        "quality_scores": score_history,
    }, why2_result


def _make_proportional_assessment_numerically_passing(
    updates: dict[str, object],
) -> None:
    """Keep authoritative SAGE FAIL while making Understanding numeric PASS."""
    evidence = dict(updates["understanding_evidence"])
    report_path = Path(str(evidence["path"]))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["scores"]["overall"] = 0.90
    report["gates"]["overall"].update(
        {
            "score": 0.90,
            "pass": True,
            "numeric_pass": True,
        }
    )
    report["pass"] = True
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
    evidence.update({"digest": digest, "pass": True, "failing_gates": []})
    updates["understanding_evidence"] = evidence
    updates["quality_scores"][-1].update(
        {"pass": True, "overall": 0.90, "evidence_digest": digest}
    )


def _make_authoritative_sage_assessment_passing(ctrl: SquadController) -> None:
    spec_dir = ctrl._project_root / "runs/run-test/specs/001-demo"
    (spec_dir / "issues.md").write_text(
        """# Issues — WHY2

## Summary
- **CRITICAL:** 0
- **HIGH:** 0
- **MEDIUM:** 0
- **LOW:** 0
- **Verdict:** PASS

## Issues

No issues found.
""",
        encoding="utf-8",
    )


def _start_proportional_quality_loop(
    tmp_path: Path,
    *,
    automatic_consumed: int = 0,
    squad_dir: Path | None = None,
) -> tuple[SquadController, SquadStateStore]:
    ctrl, store = _controller(tmp_path, squad_dir=squad_dir)
    store.initialize(
        "r",
        "greenfield",
        "msg",
        0,
        "phase1-why2",
        max_iterations=10,
        autonomy_mode="semi",
        spec_authoring_mode="proportional",
    )
    state = store.load()
    state.update(
        {
            "spec_id": "001-demo",
            "spec_dir": "runs/run-test/specs/001-demo",
        }
    )
    repair = dict(state["phase1_quality_repair"])
    repair["automatic_consumed"] = automatic_consumed
    state["phase1_quality_repair"] = repair
    store.save(state)
    return ctrl, store


def _route_understanding_assessment(
    ctrl: SquadController,
    store: SquadStateStore,
    assessment_updates: dict[str, object],
) -> str:
    return _coordinate_prepared_result(
        ctrl,
        ctrl._graph.get("phase1-understanding"),
        SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": assessment_updates,
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        ),
    )


def _run_proportional_quality_loop(
    tmp_path: Path,
    *,
    change_what: bool = True,
    automatic_consumed: int = 0,
    autonomy_mode: str = "semi",
    commander_results: tuple[SquadAgentResult, ...] = (),
    qualitative_only: bool = False,
    squad_dir: Path | None = None,
) -> tuple[SquadController, SquadStateStore, dict[str, int]]:
    """Run the production dispatch loop with only the external agents faked."""
    provider = _mock_provider()
    ctrl, store = _controller(
        tmp_path,
        provider=provider,
        squad_dir=squad_dir,
    )
    store.initialize(
        "r",
        "greenfield",
        "msg",
        0,
        "phase1-why2",
        max_iterations=10,
        autonomy_mode=autonomy_mode,
        spec_authoring_mode="proportional",
    )
    _mark_constitution_complete(tmp_path, store)
    state = store.load()
    state.update(
        {
            "spec_id": "001-demo",
            "spec_dir": "runs/run-test/specs/001-demo",
        }
    )
    repair = dict(state["phase1_quality_repair"])
    repair["automatic_consumed"] = automatic_consumed
    state["phase1_quality_repair"] = repair
    store.save(state)
    initial_updates, _why2 = _proportional_assessment_fixture(ctrl, store, 0)
    if qualitative_only:
        _make_proportional_assessment_numerically_passing(initial_updates)
    state = store.load()
    state.update(initial_updates)
    store.save(state)
    calls = {"why2": 0, "what": 0, "understanding": 0}
    commander_iterator = iter(commander_results)

    def exec_agent(_root: str, prompt: str, **_kwargs: object) -> SquadAgentResult:
        if "# COMMANDER DECISION RESOLUTION" in prompt:
            try:
                return next(commander_iterator)
            except StopIteration as exc:
                raise AssertionError(
                    "proportional test dispatched an unexpected COMMANDER attempt"
                ) from exc
        if "# Phase: phase1-why2" in prompt:
            calls["why2"] += 1
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "FAIL",
                    "state_updates": {
                        "evidence_resolution_status": "not_required",
                        "finding_routes": {
                            "findings": [
                                {
                                    "issue_id": f"ISS-QUALITY-{calls['understanding']}",
                                    "route": "spec_repair",
                                    "rationale": "Repair the residual quality debt.",
                                }
                            ]
                        },
                    },
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )
        if "# Phase: phase1-what" in prompt:
            calls["what"] += 1
            spec_dir = tmp_path / "runs/run-test/specs/001-demo"
            if change_what:
                (spec_dir / "spec.md").write_text(
                    f"# Candidate repair {calls['what']}\n\n"
                    f"- FR-001: The system shall render repair {calls['what']}.\n",
                    encoding="utf-8",
                )
            return SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "output_files": [
                        str(spec_dir / "spec.md"),
                        str(spec_dir / "requirements-overview.md"),
                    ],
                    "state_updates": {
                        "evidence_resolution_status": "not_required",
                    },
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )
        raise AssertionError("proportional test dispatched an unexpected agent phase")

    provider.exec_agent.side_effect = exec_agent

    def understanding_execute(_node: PhaseNode, _store: SquadStateStore) -> SquadAgentResult:
        calls["understanding"] += 1
        spec_path = tmp_path / "runs/run-test/specs/001-demo/spec.md"
        updates, _result = _proportional_assessment_fixture(
            ctrl,
            store,
            calls["understanding"],
            spec_text=spec_path.read_text(encoding="utf-8"),
        )
        if qualitative_only:
            _make_proportional_assessment_numerically_passing(updates)
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": updates},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

    ctrl._executors["deterministic_understanding"] = SimpleNamespace(
        execute=understanding_execute
    )
    return ctrl, store, calls


def _older_best_proportional_quality_loop(
    tmp_path: Path,
    *,
    baseline_overview_text: str | None = None,
) -> tuple[SquadController, SquadStateStore, str]:
    """Prepare a failing newer assessment whose ranked best is candidate zero."""
    ctrl, store = _start_proportional_quality_loop(tmp_path)
    _mark_constitution_complete(tmp_path, store)
    baseline_updates, baseline_result = _proportional_assessment_fixture(
        ctrl,
        store,
        0,
        score=0.60,
        spec_text="# Best candidate\n\n- FR-001: Best.\n",
        overview_text=baseline_overview_text,
    )
    state = store.load()
    state.update(baseline_updates)
    store.save(state)
    assert _coordinate_prepared_result(
        ctrl,
        ctrl._graph.get("phase1-why2"),
        baseline_result,
    ) == "phase1-what"

    state = store.load()
    repair = dict(state["phase1_quality_repair"])
    repair["automatic_consumed"] = 3
    state.update(
        {
            "phase": "phase1-why2",
            "status": "running",
            "phase1_quality_repair": repair,
        }
    )
    state.pop("blocked_reason", None)
    state.pop("quality_gate_remediation", None)
    store.save(state)

    current_text = "# Worse current candidate\n\n- FR-001: Worse.\n"
    current_updates, current_result = _proportional_assessment_fixture(
        ctrl,
        store,
        1,
        score=0.50,
        spec_text=current_text,
    )
    state = store.load()
    state.update(current_updates)
    store.save(state)
    ctrl._provider.exec_agent.side_effect = None
    ctrl._provider.exec_agent.return_value = current_result
    return ctrl, store, current_text


def _proportional_history_then_unchanged_what(
    tmp_path: Path,
    *,
    assessments: tuple[tuple[int, float], ...],
) -> tuple[SquadController, SquadStateStore]:
    """Persist assessment history with explicit repair numbers, then no-op WHAT."""
    ctrl, store = _start_proportional_quality_loop(tmp_path)
    _mark_constitution_complete(tmp_path, store)
    for assessment_index, (repair_number, score) in enumerate(assessments):
        state = store.load()
        repair = dict(state["phase1_quality_repair"])
        repair["automatic_consumed"] = repair_number
        state.update(
            {
                "phase": "phase1-why2",
                "status": "running",
                "phase1_quality_repair": repair,
            }
        )
        state.pop("blocked_reason", None)
        state.pop("quality_gate_remediation", None)
        updates, result = _proportional_assessment_fixture(
            ctrl,
            store,
            assessment_index,
            score=score,
        )
        state.update(updates)
        store.save(state)
        assert _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            result,
        ) == "phase1-what"

    state = store.load()
    repair = dict(state["phase1_quality_repair"])
    repair["automatic_consumed"] = 3
    state["phase1_quality_repair"] = repair
    store.save(state)
    spec_dir = tmp_path / "runs/run-test/specs/001-demo"
    ctrl._provider.exec_agent.side_effect = None
    ctrl._provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DONE",
            "output_files": [
                str(spec_dir / "spec.md"),
                str(spec_dir / "requirements-overview.md"),
            ],
            "state_updates": {"evidence_resolution_status": "not_required"},
        },
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )
    return ctrl, store


class TestProportionalQualityController:
    def test_banzai_resolves_eligible_sage_issue_before_proportional_budget(
        self,
        tmp_path: Path,
    ) -> None:
        """Explicit SAGE authority drives targeted repair without spending a loop."""
        ctrl, store = _start_proportional_quality_loop(tmp_path)
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        _make_proportional_assessment_numerically_passing(updates)
        issues_path = tmp_path / "runs/run-test/specs/001-demo/issues.md"
        issues_path.write_text(
            issues_path.read_text(encoding="utf-8")
            .replace("- **CRITICAL:** 0", "- **CRITICAL:** 1")
            .replace("- **LOW:** 1", "- **LOW:** 0")
            .replace("ISS-QUALITY-0", "ISS-001")
            .replace("**Severity:** LOW", "**Severity:** CRITICAL")
            .replace("**Type:** incompleteness", "**Type:** contradiction")
            .replace(
                "Repair the certified failing dimension.",
                "Treat checkpoint inventory as authoritative when restoring a player.",
            )
            .replace(
                "Immutable Understanding evidence.",
                "The checkpoint requirements explicitly include inventory state.",
            )
            .replace("**Banzai eligible:** no", "**Banzai eligible:** yes"),
            encoding="utf-8",
        )
        finding = why2.echelon_result["state_updates"]["finding_routes"][
            "findings"
        ][0]
        finding["issue_id"] = "ISS-001"
        state = store.load()
        state.update(updates)
        state["autonomy_mode"] = "banzai"
        store.save(state)

        route = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            why2,
        )

        persisted = store.load()
        assert route == "terminal-blocked"
        assert persisted["phase"] == "phase1-what"
        assert persisted["status"] == "running"
        assert persisted["blocked_decision"]["resolved_by"] == "controller"
        assert persisted["selected_issue_resolution"] == "ISS-001"
        selected = persisted["issue_resolution_ledger"]["ISS-001"]
        assert selected["status"] == "selected"
        assert selected["decision"] == (
            "Treat checkpoint inventory as authoritative when restoring a player."
        )
        repair = persisted["phase1_quality_repair"]
        assert repair["automatic_consumed"] == 0
        assert repair["candidate_ids"] == []
        assert "quality_gate_remediation" not in persisted
        ctrl._provider.exec_agent.assert_not_called()

    def test_pending_evidence_routes_to_investigator_before_proportional_repair(
        self,
        tmp_path: Path,
    ) -> None:
        """A valid evidence request is workflow routing, not candidate corruption."""
        ctrl, store = _start_proportional_quality_loop(tmp_path)
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        why2_updates = why2.echelon_result["state_updates"]
        why2_updates["evidence_resolution_status"] = "pending"
        why2_updates["evidence_requests"] = {
            "requests": [
                {
                    "id": "ER-001",
                    "question": "Which browser baseline is authoritative?",
                    "affected_requirements": ["FR-001"],
                    "evidence_needed": "A declared support baseline.",
                    "supplied_reference_ids": ["IN-REF-001"],
                }
            ]
        }
        why2_updates["finding_routes"]["findings"][0]["route"] = (
            "evidence_resolution"
        )
        state = store.load()
        state.update(updates)
        store.save(state)

        route = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            why2,
        )

        persisted = store.load()
        assert route == "phase1-investigate"
        assert persisted.get("blocked_reason") is None
        assert persisted["phase1_quality_repair"]["candidate_ids"] == []

    def test_restart_migrates_v2_proportional_decision_from_candidate_authority(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store, _calls = _run_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
            autonomy_mode="semi",
        )
        result = ctrl.run("msg", "semi")
        sealed_state = store.load()
        sealed = sealed_state["blocked_decision"]
        assert result.status == "blocked"
        assert sealed["schema_version"] == 3
        assert sealed["producer_id"] == (
            "proportional_quality_budget_exhausted"
        )
        legacy = build_blocked_decision_v2(
            decision_id=str(sealed["id"]),
            status="pending",
            source_kind=str(sealed["source_kind"]),
            producer_id=str(sealed["producer_id"]),
            source_phase=str(sealed["source_phase"]),
            reason_code=str(sealed["reason_code"]),
            classification=str(sealed["classification"]),
            question=str(sealed["question"]),
            options=[
                {**dict(option), "recommended": False}
                for option in sealed["options"]
            ],
            recommended_answer=sealed["recommended_answer"],
            risk_level=sealed["risk_level"],
            resolution_handler=str(sealed["resolution_handler"]),
            autonomy_mode="banzai",
            source_state_revision=int(sealed["source_state_revision"]),
            now=str(sealed["created_at"]),
        )
        legacy_state = dict(sealed_state)
        legacy_state.update(
            {
                "autonomy_mode": "banzai",
                "status": "blocked",
                "blocked_decision": legacy,
                "recovery_instruction": RecoveryInstruction(
                    kind=RecoveryKind.RESOLVE_DECISION,
                    reason_code=str(legacy["reason_code"]),
                    phase=str(legacy["source_phase"]),
                    requires_human_input=False,
                    schema_version=2,
                    decision_id=str(legacy["id"]),
                ).to_dict(),
            }
        )
        store._path.write_text(json.dumps(legacy_state), encoding="utf-8")
        provider = MagicMock()
        restarted = SquadController(
            provider=provider,
            state_store=store,
            phase_graph=PhaseGraph(
                DEFINITION,
                prosaic_subagents_dir=PROSAIC_SUBAGENTS,
            ),
            ext_dir=EXT_ROOT / "runtime",
            project_root=tmp_path,
            squad_dir=store.squad_dir,
        )

        migrated = restarted._migrate_pending_v2_banzai_decision(
            store.load(),
            legacy,
        )

        assert migrated is not None
        current = store.load()["blocked_decision"]
        assert current["schema_version"] == 3
        assert current["id"] == legacy["id"]
        assert current["recommended_option_id"] == sealed[
            "recommended_option_id"
        ]
        assert current["recommendation_evidence"] == sealed[
            "recommendation_evidence"
        ]
        provider.exec_agent.assert_not_called()

    def test_repairable_sage_contradiction_routes_to_what_not_candidate_integrity(
        self,
        tmp_path: Path,
    ) -> None:
        """A valid SAGE contradiction is a repairable quality failure, not corrupt state."""
        ctrl, store = _start_proportional_quality_loop(tmp_path)
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        _make_proportional_assessment_numerically_passing(updates)
        issues_path = tmp_path / "runs/run-test/specs/001-demo/issues.md"
        issues_path.write_text(
            issues_path.read_text(encoding="utf-8")
            .replace("- **HIGH:** 0", "- **HIGH:** 1")
            .replace("- **LOW:** 1", "- **LOW:** 0")
            .replace("**Severity:** LOW", "**Severity:** HIGH")
            .replace("**Type:** incompleteness", "**Type:** contradiction"),
            encoding="utf-8",
        )
        state = store.load()
        state.update(updates)
        store.save(state)

        route = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            why2,
        )

        persisted = store.load()
        assert route == "phase1-what"
        assert persisted.get("blocked_reason") is None
        assert persisted["phase1_quality_repair"]["candidate_ids"] == [
            "quality-candidate-0"
        ]
        findings = persisted["quality_gate_remediation"][
            "qualitative_findings"
        ]
        assert findings[0]["type"] == "contradiction"

    def test_explicit_advisory_sage_issue_does_not_require_a_repair_route(
        self,
        tmp_path: Path,
    ) -> None:
        """Only required SAGE amendments become proportional quality debt."""
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        issues_path = tmp_path / "runs/run-test/specs/001-demo/issues.md"
        advisory = """
### ISS-ADVISORY: Non-blocking reviewer handoff
- **Severity:** LOW
- **Type:** incompleteness
- **Description:** The test planner should derive an outcome from the requirement text.
- **Affected artifact:** spec.md
- **Affected section:** Requirements
- **Evidence:** The certified gate passes and no specification amendment is needed.
- **Recommendation:** Carry this observation into test planning.
- **Responsible agent:** HOW
- **Action Required:** None — advisory. No amendment requested.

"""
        issues_path.write_text(
            issues_path.read_text(encoding="utf-8")
            .replace("- **LOW:** 1", "- **LOW:** 2")
            .replace("### Resolution Guidance", advisory + "### Resolution Guidance"),
            encoding="utf-8",
        )
        state = store.load()
        state.update(updates)
        store.save(state)

        next_phase = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            why2,
        )

        persisted = store.load()
        assert next_phase == "terminal-blocked"
        assert "blocked_decision" in persisted
        assert persisted.get("blocked_reason") != (
            "proportional_quality_candidate_integrity_failed"
        )
        assert persisted["phase1_quality_repair"]["candidate_ids"] == [
            "quality-candidate-0"
        ]

        assert ctrl.resume_with_human_input("continue_with_debt") is True
        accepted = store.load()
        assert [
            finding["issue_id"]
            for finding in accepted["spec_quality_debt_authorization"][
                "qualitative_debt"
            ]
        ] == ["ISS-QUALITY-0"]

    def test_passing_sage_advisories_do_not_become_integrity_failures(
        self,
        tmp_path: Path,
    ) -> None:
        """A PASS may preserve advisory handoffs without blocking progress."""
        ctrl, store = _start_proportional_quality_loop(tmp_path)
        updates, result = _proportional_assessment_fixture(ctrl, store, 0)
        _make_proportional_assessment_numerically_passing(updates)
        _make_authoritative_sage_assessment_passing(ctrl)
        issues_path = tmp_path / "runs/run-test/specs/001-demo/issues.md"
        advisory = """### ISS-ADVISORY: Non-blocking reviewer handoff
- **Severity:** LOW
- **Type:** incompleteness
- **Description:** The test planner should derive an outcome from the requirement text.
- **Affected artifact:** spec.md
- **Affected section:** Requirements
- **Evidence:** The certified gate passes and no specification amendment is needed.
- **Recommendation:** Carry this observation into test planning.
- **Responsible agent:** HOW
- **Action Required:** None — advisory. No amendment requested.

"""
        issues_path.write_text(
            issues_path.read_text(encoding="utf-8")
            .replace("- **LOW:** 0", "- **LOW:** 1")
            .replace("No issues found.\n", advisory),
            encoding="utf-8",
        )
        result.echelon_result["verdict"] = "PASS"
        result.echelon_result["state_updates"]["finding_routes"] = {
            "findings": []
        }
        state = store.load()
        state.update(updates)
        store.save(state)

        route = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            result,
        )

        persisted = store.load()
        assert route == "phase1-lexicon-derive"
        assert persisted.get("blocked_reason") is None
        assert persisted["phase1_quality_repair"]["candidate_ids"] == [
            "quality-candidate-0"
        ]

    def test_replaced_sage_evidence_between_assessment_and_candidate_fails_closed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(tmp_path)
        updates, result = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(updates)
        store.save(state)
        issues_path = tmp_path / "runs/run-test/specs/001-demo/issues.md"
        replacement = issues_path.with_suffix(".replacement.md")
        replacement.write_bytes(
            issues_path.read_bytes() + b"\n<!-- replaced -->\n"
        )
        real_prepare = squad_module.prepare_quality_candidate

        def replace_before_candidate_preparation(*args, **kwargs):
            replacement.replace(issues_path)
            return real_prepare(*args, **kwargs)

        monkeypatch.setattr(
            squad_module,
            "prepare_quality_candidate",
            replace_before_candidate_preparation,
        )

        route = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            result,
        )

        persisted = store.load()
        assert route == "terminal-blocked"
        assert persisted["blocked_reason"] == (
            "proportional_quality_candidate_integrity_failed"
        )
        assert persisted["phase1_quality_repair"]["candidate_ids"] == []

    def test_replaced_sage_evidence_between_assessment_and_certificate_fails_closed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(tmp_path)
        updates, result = _proportional_assessment_fixture(ctrl, store, 0)
        _make_proportional_assessment_numerically_passing(updates)
        _make_authoritative_sage_assessment_passing(ctrl)
        result.echelon_result["verdict"] = "PASS"
        result.echelon_result["state_updates"]["finding_routes"] = {
            "findings": []
        }
        state = store.load()
        state.update(updates)
        store.save(state)
        issues_path = tmp_path / "runs/run-test/specs/001-demo/issues.md"
        replacement = issues_path.with_suffix(".replacement.md")
        replacement.write_bytes(
            issues_path.read_bytes() + b"\n<!-- replaced -->\n"
        )
        real_capture = ctrl._capture_proportional_quality_candidate

        def capture_then_replace(*args, **kwargs):
            captured = real_capture(*args, **kwargs)
            replacement.replace(issues_path)
            return captured

        monkeypatch.setattr(
            ctrl,
            "_capture_proportional_quality_candidate",
            capture_then_replace,
        )

        node = ctrl._graph.get("phase1-why2")
        snapshot = ctrl._state_store.capture_routing_snapshot(
            expected_phase=node.id
        )
        route, routing_updates, _request = ctrl._coordinate_why_transition_state(
            node,
            ctrl._prepare_phase_result(node, result, snapshot),
            snapshot,
        )

        assert route == "terminal-blocked"
        assert routing_updates["blocked_reason"] == (
            "spec_quality_certificate_unavailable"
        )
        assert "spec_quality_certificate" not in routing_updates
        assert store.load()["phase1_quality_repair"]["candidate_ids"] == []

    def test_numeric_and_provider_pass_cannot_certify_sage_fail(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(tmp_path)
        updates, result = _proportional_assessment_fixture(ctrl, store, 0)
        _make_proportional_assessment_numerically_passing(updates)
        result.echelon_result["verdict"] = "PASS"
        state = store.load()
        state.update(updates)
        store.save(state)

        route = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            result,
        )

        persisted = store.load()
        assert route != "phase1-lexicon-derive"
        assert persisted["blocked_reason"] == (
            "proportional_quality_candidate_integrity_failed"
        )
        assert "spec_quality_certificate" not in persisted

    def test_critical_sage_fail_blocks_when_other_verdicts_pass(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(tmp_path)
        updates, result = _proportional_assessment_fixture(ctrl, store, 0)
        _make_proportional_assessment_numerically_passing(updates)
        result.echelon_result["verdict"] = "PASS"
        issues = tmp_path / "runs/run-test/specs/001-demo/issues.md"
        issues.write_text(
            issues.read_text(encoding="utf-8")
            .replace("- **CRITICAL:** 0", "- **CRITICAL:** 1")
            .replace("- **LOW:** 1", "- **LOW:** 0")
            .replace("- **Severity:** LOW", "- **Severity:** CRITICAL"),
            encoding="utf-8",
        )
        state = store.load()
        state.update(updates)
        store.save(state)

        route = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            result,
        )

        assert route == "terminal-blocked"
        assert store.load()["blocked_reason"] == (
            "proportional_quality_candidate_integrity_failed"
        )
        assert "spec_quality_certificate" not in store.load()

    def test_provider_sage_mismatch_is_certification_integrity_failure(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(tmp_path)
        updates, result = _proportional_assessment_fixture(ctrl, store, 0)
        _make_proportional_assessment_numerically_passing(updates)
        _make_authoritative_sage_assessment_passing(ctrl)
        state = store.load()
        state.update(updates)
        store.save(state)

        route = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            result,
        )

        assert route == "terminal-blocked"
        assert store.load()["blocked_reason"] == (
            "proportional_quality_candidate_integrity_failed"
        )
        assert "spec_quality_certificate" not in store.load()

    def test_recommendation_compares_latest_distinct_repairs_with_audit_history(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _proportional_history_then_unchanged_what(
            tmp_path,
            assessments=((0, 0.76), (1, 0.74), (1, 0.75)),
        )

        result = ctrl.run("msg", "semi")

        blocked = store.load()
        assert result.status == "blocked"
        decision = blocked["blocked_decision"]
        assert next(
            option["id"]
            for option in decision["options"]
            if option["recommended"] is True
        ) == "continue_with_debt"
        recommendation = blocked["proportional_quality_candidate_evidence"][
            "recommendation_evidence"
        ]
        assert recommendation["comparison_previous_candidate_id"] == (
            "quality-candidate-0"
        )
        assert recommendation["comparison_current_candidate_id"] == (
            "quality-candidate-2"
        )
        assert [
            entry["repair_number"] for entry in recommendation["score_history"]
        ] == [0, 1]
        assert recommendation["per_repair_deltas"] == [
            {
                "repair_number": 1,
                "previous_repair_number": 0,
                "previous_candidate_id": "quality-candidate-0",
                "current_candidate_id": "quality-candidate-2",
                "score_deltas": [{"name": "overall", "delta": -0.01}],
                "formal_statement_delta": 0,
                "byte_delta": 0,
            }
        ]

    def test_unchanged_final_what_never_recommends_extension(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _proportional_history_then_unchanged_what(
            tmp_path,
            assessments=((0, 0.70), (1, 0.76)),
        )

        ctrl.run("msg", "semi")

        blocked = store.load()
        assert blocked["proportional_quality_candidate_evidence"][
            "last_repair_outcome"
        ] == "no_artifact_progress"
        assert next(
            option["id"]
            for option in blocked["blocked_decision"]["options"]
            if option["recommended"] is True
        ) == "continue_with_debt"
        assert "no artifact progress" in blocked[
            "proportional_quality_candidate_evidence"
        ]["recommendation_evidence"]["rationale"].lower()

    def test_incomplete_authoritative_sage_route_coverage_fails_before_decision(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        _mark_constitution_complete(tmp_path, store)
        updates, result = _proportional_assessment_fixture(ctrl, store, 0)
        spec_dir = tmp_path / "runs/run-test/specs/001-demo"
        issues = spec_dir / "issues.md"
        content = issues.read_text(encoding="utf-8")
        content = content.replace("- **LOW:** 1", "- **LOW:** 2")
        content = content.replace(
            "### Resolution Guidance",
            """### ISS-QUALITY-MISSING: Unrouted quality debt
- **Severity:** LOW
- **Type:** ambiguity
- **Description:** A second authoritative quality issue remains.
- **Affected artifact:** spec.md
- **Affected section:** Requirements
- **Evidence:** The second issue is present only in the authoritative ledger.
- **Recommendation:** Repair the ambiguous requirement.
- **Responsible agent:** WHAT
- **Action Required:** Amend the specification.

### Resolution Guidance""",
        )
        issues.write_text(content, encoding="utf-8")
        state = store.load()
        state.update(updates)
        store.save(state)
        ctrl._provider.exec_agent.side_effect = None
        ctrl._provider.exec_agent.return_value = result

        run = ctrl.run("msg", "semi")

        failed = store.load()
        assert run.status == "blocked"
        assert failed["blocked_reason"] == (
            "proportional_quality_candidate_integrity_failed"
        )
        assert "blocked_decision" not in failed
        assert failed["phase1_quality_repair"]["candidate_ids"] == []

    def test_duplicate_authoritative_sage_route_fails_before_decision(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        _mark_constitution_complete(tmp_path, store)
        updates, result = _proportional_assessment_fixture(ctrl, store, 0)
        findings = result.echelon_result["state_updates"]["finding_routes"][
            "findings"
        ]
        findings.append(dict(findings[0]))
        state = store.load()
        state.update(updates)
        store.save(state)
        ctrl._provider.exec_agent.side_effect = None
        ctrl._provider.exec_agent.return_value = result

        run = ctrl.run("msg", "semi")

        failed = store.load()
        assert run.status == "blocked"
        assert failed["blocked_reason"] == (
            "proportional_quality_candidate_integrity_failed"
        )
        assert "blocked_decision" not in failed
        assert failed["phase1_quality_repair"]["candidate_ids"] == []

    def test_qualitative_only_sage_failure_accepts_executable_human_debt(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        _mark_constitution_complete(tmp_path, store)
        updates, result = _proportional_assessment_fixture(ctrl, store, 0)
        _make_proportional_assessment_numerically_passing(updates)
        state = store.load()
        state.update(updates)
        store.save(state)

        route = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            result,
        )

        blocked = store.load()
        assert route == "terminal-blocked"
        assert blocked["blocked_reason"] == (
            "proportional_quality_budget_exhausted"
        )
        assert blocked["understanding_evidence"]["pass"] is True
        assert blocked["proportional_quality_candidate_evidence"][
            "failed_gates"
        ] == []
        assert blocked["proportional_quality_candidate_evidence"][
            "sage_finding_routes"
        ][0]["issue_id"] == "ISS-QUALITY-0"
        assert next(
            option["id"]
            for option in blocked["blocked_decision"]["options"]
            if option["recommended"] is True
        ) == "continue_with_debt"

        assert ctrl.resume_with_human_input("continue_with_debt") is True

        accepted = store.load()
        authorization = accepted["spec_quality_debt_authorization"]
        assert authorization["failed_gates"] == []
        assert authorization["qualitative_debt"][0]["issue_id"] == (
            "ISS-QUALITY-0"
        )
        debt = json.loads(
            (
                tmp_path
                / "runs/run-test/specs/001-demo/quality-debt.json"
            ).read_text(encoding="utf-8")
        )
        assert debt["failed_gates"] == []
        assert debt["qualitative_debt"] == authorization[
            "qualitative_debt"
        ]
        from harness.phase1_quality_debt import (
            has_current_quality_debt_authorization,
        )

        assert has_current_quality_debt_authorization(
            accepted,
            project_root=tmp_path,
        )
        ctrl._materialize_controller_phase_inputs(
            ctrl._graph.get("phase3-plan")
        )
        debt_context = store.load()["spec_quality_debt_context"]
        assert debt_context["status"] == "accepted_with_debt"
        assert debt_context["failed_gates"] == []
        assert debt_context["qualitative_debt"] == authorization[
            "qualitative_debt"
        ]

    def test_qualitative_only_sage_failure_uses_controller_evidence_in_banzai(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store, _calls = _run_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
            autonomy_mode="banzai",
            qualitative_only=True,
        )

        result = ctrl.run_single_phase(
            "phase1-why2",
            user_message="resolve qualitative proportional quality",
            mode="banzai",
        )

        state = store.load()
        assert result.status == "running"
        assert state["blocked_decision"]["resolved_by"] == "controller"
        authorization = state["spec_quality_debt_authorization"]
        assert authorization["resolved_by"] == "controller"
        assert authorization["failed_gates"] == []
        assert authorization["qualitative_debt"][0]["issue_id"] == (
            "ISS-QUALITY-0"
        )
        ctrl._materialize_controller_phase_inputs(
            ctrl._graph.get("phase3-plan")
        )
        debt_context = store.load()["spec_quality_debt_context"]
        assert debt_context["failed_gates"] == []
        assert debt_context["qualitative_debt"] == authorization[
            "qualitative_debt"
        ]

    @pytest.mark.parametrize(
        "route_problem",
        ["missing", "duplicate", "empty", "non_spec_repair"],
    )
    def test_qualitative_only_failure_requires_exact_authoritative_route_coverage(
        self,
        tmp_path: Path,
        route_problem: str,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        _mark_constitution_complete(tmp_path, store)
        updates, result = _proportional_assessment_fixture(ctrl, store, 0)
        _make_proportional_assessment_numerically_passing(updates)
        findings = result.echelon_result["state_updates"]["finding_routes"][
            "findings"
        ]
        if route_problem == "duplicate":
            findings.append(dict(findings[0]))
        elif route_problem == "empty":
            findings.clear()
            result.echelon_result["verdict"] = "PASS"
        elif route_problem == "non_spec_repair":
            findings[0]["route"] = "human_decision"
        else:
            issues = (
                tmp_path / "runs/run-test/specs/001-demo/issues.md"
            )
            content = issues.read_text(encoding="utf-8")
            content = content.replace("- **LOW:** 1", "- **LOW:** 2")
            content = content.replace(
                "### Resolution Guidance",
                """### ISS-QUALITY-MISSING: Unrouted qualitative debt
- **Severity:** LOW
- **Type:** ambiguity
- **Description:** A second authoritative issue remains.
- **Affected artifact:** spec.md
- **Affected section:** Requirements
- **Evidence:** The authoritative SAGE ledger records this issue.
- **Recommendation:** Repair the ambiguity.
- **Responsible agent:** WHAT
- **Action Required:** Amend the specification.

### Resolution Guidance""",
            )
            issues.write_text(content, encoding="utf-8")
        state = store.load()
        state.update(updates)
        store.save(state)

        _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            result,
        )

        failed = store.load()
        assert failed["blocked_reason"] == (
            "proportional_quality_candidate_integrity_failed"
        )
        assert "blocked_decision" not in failed
        assert failed["phase1_quality_repair"]["candidate_ids"] == []

    def test_older_ranked_candidate_debt_remains_current_after_completion(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store, _current_text = _older_best_proportional_quality_loop(
            tmp_path
        )

        decision = ctrl.run("msg", "semi")

        blocked = store.load()
        assert decision.status == "blocked"
        evidence = blocked["proportional_quality_candidate_evidence"]
        assert evidence["current_candidate_id"] == "quality-candidate-1"
        assert evidence["selected_candidate_id"] == "quality-candidate-0"
        selected_manifest = (
            ctrl._squad_dir
            / "quality-candidates/quality-candidate-0.json"
        )
        selected_digest = hashlib.sha256(
            selected_manifest.read_bytes()
        ).hexdigest()
        assert evidence["candidate_manifest_sha256"] == selected_digest

        assert ctrl.resume_with_human_input("continue_with_debt") is True

        accepted = store.load()
        assert accepted["proportional_quality_candidate_evidence"][
            "candidate_manifest_sha256"
        ] == selected_digest
        assert ctrl._guard_phase1_quality_evidence("checkpoint-assess") == (
            "checkpoint-assess"
        )

    def test_restore_crash_after_first_exchange_recovers_once(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _current_text = _older_best_proportional_quality_loop(
            tmp_path
        )
        spec_dir = tmp_path / "runs/run-test/specs/001-demo"
        crashed = False

        def interrupt_during_restore(point: str) -> None:
            nonlocal crashed
            if point == "after_first_exchange" and not crashed:
                crashed = True
                raise KeyboardInterrupt(
                    "interrupted after the first candidate artifact replacement"
                )

        monkeypatch.setattr(
            git_first_restore_module,
            "_restore_fault",
            interrupt_during_restore,
        )

        with pytest.raises(KeyboardInterrupt, match="first candidate artifact"):
            ctrl.run("msg", "semi")

        interrupted = store.load()
        assert interrupted[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == (
            "quality"
        )
        assert crashed is True
        candidate = json.loads(
            (
                ctrl._squad_dir
                / "quality-candidates/quality-candidate-0.json"
            ).read_text(encoding="utf-8")
        )
        postimages = candidate["owned_artifact_digests"]
        observed = {
            name: hashlib.sha256((spec_dir / name).read_bytes()).hexdigest()
            for name in sorted(postimages)
        }
        assert any(observed[name] == postimages[name] for name in observed)
        assert any(observed[name] != postimages[name] for name in observed)

        monkeypatch.setattr(
            git_first_restore_module,
            "_restore_fault",
            lambda _point: None,
        )
        del ctrl
        fresh, fresh_store = _controller(tmp_path)

        result = fresh.run("recover candidate restoration", "semi")

        recovered = fresh_store.load()
        assert result.status == "blocked"
        assert PENDING_CONTROLLER_COMPLETION_KEY not in recovered
        assert recovered["blocked_reason"] == (
            "proportional_quality_budget_exhausted"
        )
        assert {
            name: hashlib.sha256((spec_dir / name).read_bytes()).hexdigest()
            for name in sorted(postimages)
        } == postimages
        ledger = json.loads(
            (spec_dir / ".echelon/checkpoints.json").read_text(encoding="utf-8")
        )
        restored = [
            row
            for row in ledger["checkpoints"]
            if row["phase"] == "phase1-quality-candidate-restored"
        ]
        assert len(restored) == 1

    def test_restore_index_install_rejects_concurrent_unrelated_staging(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _current_text = _older_best_proportional_quality_loop(
            tmp_path
        )
        unrelated = tmp_path / "concurrent-stage.txt"
        staged_bytes = b"preserve this unrelated stage\n"
        real_git = git_first_restore_module._git
        real_fault = git_first_restore_module._restore_fault
        injected = False

        def stage_unrelated() -> None:
            nonlocal injected
            if injected:
                return
            injected = True
            unrelated.write_bytes(staged_bytes)
            subprocess.run(
                ["git", "add", "--", unrelated.name],
                cwd=tmp_path,
                check=True,
                capture_output=True,
            )

        def inject_at_safe_install(point: str) -> None:
            if point == "before_index_install":
                stage_unrelated()
            real_fault(point)

        def inject_at_legacy_install(
            project_root: Path,
            *args: str,
            **kwargs: object,
        ):
            if args[:1] == ("read-tree",) and kwargs.get("env") is None:
                stage_unrelated()
            return real_git(project_root, *args, **kwargs)

        monkeypatch.setattr(
            git_first_restore_module,
            "_restore_fault",
            inject_at_safe_install,
        )
        monkeypatch.setattr(
            git_first_restore_module,
            "_git",
            inject_at_legacy_install,
        )

        result = ctrl.run("preserve a concurrent staged path", "semi")

        failed = store.load()
        assert injected is True
        assert result.status == "blocked"
        assert failed[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == "quality"
        assert failed["controller_completion_failure"]["code"] == (
            "receipts_mismatch"
        )
        assert subprocess.run(
            ["git", "show", f":{unrelated.name}"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        ).stdout == staged_bytes
        ledger = json.loads(
            (
                tmp_path
                / "runs/run-test/specs/001-demo/.echelon/checkpoints.json"
            ).read_text(encoding="utf-8")
        )
        assert not any(
            row["phase"] == "phase1-quality-candidate-restored"
            for row in ledger["checkpoints"]
        )

    def test_pending_restore_retry_rejects_symlinked_active_index(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _current_text = _older_best_proportional_quality_loop(
            tmp_path
        )
        real_materialize = (
            quality_effects_module.materialize_quality_candidate_restore
        )

        def interrupt_before_restore(*_args: object, **_kwargs: object):
            raise KeyboardInterrupt("interrupt before candidate restore")

        monkeypatch.setattr(
            quality_effects_module,
            "materialize_quality_candidate_restore",
            interrupt_before_restore,
        )
        with pytest.raises(KeyboardInterrupt, match="before candidate restore"):
            ctrl.run("prepare a retry with active index drift", "semi")
        monkeypatch.setattr(
            quality_effects_module,
            "materialize_quality_candidate_restore",
            real_materialize,
        )

        index_output = subprocess.run(
            ["git", "rev-parse", "--git-path", "index"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        index_path = Path(index_output)
        if not index_path.is_absolute():
            index_path = tmp_path / index_path
        victim = tmp_path / "active-index-victim"
        index_path.rename(victim)
        victim_bytes = victim.read_bytes()
        index_path.symlink_to(victim)

        del ctrl
        fresh, fresh_store = _controller(tmp_path)
        result = fresh.run("retry without following active index", "semi")

        failed = fresh_store.load()
        assert result.status == "blocked"
        assert failed[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == "quality"
        assert failed["controller_completion_failure"]["code"] == (
            "receipts_mismatch"
        )
        assert index_path.is_symlink()
        assert victim.read_bytes() == victim_bytes
        ledger = json.loads(
            (
                tmp_path
                / "runs/run-test/specs/001-demo/.echelon/checkpoints.json"
            ).read_text(encoding="utf-8")
        )
        assert not any(
            row["phase"] == "phase1-quality-candidate-restored"
            for row in ledger["checkpoints"]
        )

    def test_restore_retry_preserves_unrelated_owned_artifact_drift(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _current_text = _older_best_proportional_quality_loop(
            tmp_path
        )
        spec_dir = tmp_path / "runs/run-test/specs/001-demo"
        target = spec_dir / "requirements-overview.md"
        drift = b"# Unrelated third-party drift\n"
        real_materialize = (
            quality_effects_module.materialize_quality_candidate_restore
        )
        injected = False

        def drift_before_restore(*args: object, **kwargs: object):
            nonlocal injected
            if not injected:
                injected = True
                target.write_bytes(drift)
            return real_materialize(*args, **kwargs)

        monkeypatch.setattr(
            quality_effects_module,
            "materialize_quality_candidate_restore",
            drift_before_restore,
        )

        result = ctrl.run("preserve unrelated restore drift", "semi")

        failed = store.load()
        assert injected is True
        assert result.status == "blocked"
        assert failed[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == "quality"
        assert failed["controller_completion_failure"]["code"] == (
            "receipts_mismatch"
        )
        assert target.read_bytes() == drift
        ledger = json.loads(
            (spec_dir / ".echelon/checkpoints.json").read_text(
                encoding="utf-8"
            )
        )
        assert not any(
            row["phase"] == "phase1-quality-candidate-restored"
            for row in ledger["checkpoints"]
        )

    def test_restore_never_follows_final_component_symlink_swap(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _current_text = _older_best_proportional_quality_loop(
            tmp_path,
            baseline_overview_text="../victim",
        )
        spec_dir = tmp_path / "runs/run-test/specs/001-demo"
        target = spec_dir / "requirements-overview.md"
        victim = spec_dir.parent / "victim"
        victim.write_bytes(b"../victim")
        real_materialize = (
            quality_effects_module.materialize_quality_candidate_restore
        )
        real_lstat = Path.lstat
        armed = False
        injected = False

        def arm_restore(*args: object, **kwargs: object):
            nonlocal armed
            armed = True
            return real_materialize(*args, **kwargs)

        def swap_after_classification(path: Path):
            nonlocal injected
            metadata = real_lstat(path)
            if armed and path == target and not injected:
                injected = True
                path.unlink()
                path.symlink_to("../victim")
            return metadata

        monkeypatch.setattr(
            quality_effects_module,
            "materialize_quality_candidate_restore",
            arm_restore,
        )
        monkeypatch.setattr(Path, "lstat", swap_after_classification)

        result = ctrl.run("restore without following a symlink swap", "semi")

        armed = False
        state = store.load()
        assert result.status == "blocked"
        assert injected is False
        assert not target.is_symlink()
        assert target.read_bytes() == b"../victim"
        ledger = json.loads(
            (spec_dir / ".echelon/checkpoints.json").read_text(
                encoding="utf-8"
            )
        )
        restored = [
            row
            for row in ledger["checkpoints"]
            if row["phase"] == "phase1-quality-candidate-restored"
        ]
        assert len(restored) == 1
        tree = subprocess.run(
            [
                "git",
                "ls-tree",
                restored[0]["commit"],
                "--",
                "runs/run-test/specs/001-demo/requirements-overview.md",
            ],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        assert tree.startswith("100644 ")
        assert victim.read_bytes() == b"../victim"

    def test_pending_legacy_restore_fails_closed_before_mutation_with_guidance(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _current_text = _older_best_proportional_quality_loop(
            tmp_path
        )
        spec_dir = tmp_path / "runs/run-test/specs/001-demo"
        real_materialize = (
            quality_effects_module.materialize_quality_candidate_restore
        )

        def interrupt_before_restore(*_args: object, **_kwargs: object):
            raise KeyboardInterrupt("simulate process death before restore")

        monkeypatch.setattr(
            quality_effects_module,
            "materialize_quality_candidate_restore",
            interrupt_before_restore,
        )
        with pytest.raises(KeyboardInterrupt, match="process death"):
            ctrl.run("prepare a recoverable restore", "semi")

        marker = store.load()[PENDING_CONTROLLER_COMPLETION_KEY]
        prepared = load_prepared_controller_completion(
            tmp_path,
            ctrl._squad_dir,
            marker,
        )
        effect = prepared.intent.quality_effect
        restore_completion_id = hashlib.sha256(
            (
                f"{prepared.intent.completion_id}:quality-restore"
            ).encode("utf-8")
        ).hexdigest()[:32]
        candidate_id = str(effect["restore_candidate_id"])
        candidate = json.loads(
            (
                ctrl._squad_dir
                / "quality-candidates"
                / f"{candidate_id}.json"
            ).read_text(encoding="utf-8")
        )
        preimages = effect["restore_artifact_preimage_digests"]
        entries = []
        for name, postimage in sorted(
            candidate["owned_artifact_digests"].items()
        ):
            token = hashlib.sha256(
                f"{restore_completion_id}:{name}".encode("utf-8")
            ).hexdigest()[:24]
            entries.append(
                {
                    "artifact": name,
                    "preimage_sha256": preimages[name],
                    "postimage_sha256": postimage,
                    "temp_name": (
                        f".echelon-quality-restore-{token}.tmp"
                    ),
                }
            )
        journal_payload = {
            "schema_version": 1,
            "kind": "quality_candidate_restore_exchange",
            "completion_id": restore_completion_id,
            "candidate_id": candidate_id,
            "spec_dir": str(effect["spec_dir"]),
            "entries": entries,
        }
        journal = (
            ctrl._squad_dir
            / "quality-restore-exchanges"
            / f"{restore_completion_id}.json"
        )
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(
            json.dumps(
                journal_payload,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )

        interrupted_entry = next(
            entry
            for entry in entries
            if entry["artifact"] == "requirements-overview.md"
        )
        target = spec_dir / str(interrupted_entry["artifact"])
        displaced = spec_dir / str(interrupted_entry["temp_name"])
        preimage_content = target.read_bytes()
        relative = target.relative_to(tmp_path).as_posix()
        postimage_content = subprocess.run(
            ["git", "show", f"{candidate['checkpoint_commit']}:{relative}"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        ).stdout
        assert hashlib.sha256(preimage_content).hexdigest() == (
            interrupted_entry["preimage_sha256"]
        )
        assert hashlib.sha256(postimage_content).hexdigest() == (
            interrupted_entry["postimage_sha256"]
        )
        target.write_bytes(postimage_content)
        displaced.write_bytes(preimage_content)

        monkeypatch.setattr(
            quality_effects_module,
            "materialize_quality_candidate_restore",
            real_materialize,
        )

        def file_snapshot(root: Path) -> dict[str, tuple[int, bytes]]:
            return {
                path.relative_to(root).as_posix(): (
                    path.lstat().st_mode,
                    path.read_bytes(),
                )
                for path in root.rglob("*")
                if path.is_file()
            }

        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD^{commit}"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        index_before = subprocess.run(
            ["git", "write-tree"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        git_objects_before = file_snapshot(tmp_path / ".git/objects")
        run_before = file_snapshot(ctrl._squad_dir)
        spec_before = file_snapshot(spec_dir)
        journal_before = journal.read_bytes()

        with pytest.raises(CompletionError) as failure:
            quality_effects_module.apply_or_verify_proportional_quality_effect(
                effect,
                completion_id=prepared.intent.completion_id,
                project_root=tmp_path,
                state=store.load(),
                route=prepared.intent.route,
                preceding_checkpoint_receipt=(
                    prepared.receipts["effects"].get("checkpoint")
                ),
            )

        causes: list[str] = []
        cause: BaseException | None = failure.value
        while cause is not None:
            causes.append(str(cause))
            cause = cause.__cause__
        assert any(
            "legacy candidate restore recovery required" in message
            for message in causes
        )
        assert subprocess.run(
            ["git", "rev-parse", "HEAD^{commit}"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip() == head_before
        assert subprocess.run(
            ["git", "write-tree"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip() == index_before
        assert file_snapshot(tmp_path / ".git/objects") == git_objects_before
        assert file_snapshot(ctrl._squad_dir) == run_before
        assert file_snapshot(spec_dir) == spec_before

        del ctrl
        fresh, fresh_store = _controller(tmp_path)

        result = fresh.run("recover after the hard kill", "semi")

        recovered = fresh_store.load()
        assert result.status == "blocked"
        assert recovered[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == "quality"
        assert recovered["controller_completion_failure"]["code"] == (
            "receipts_mismatch"
        )
        assert journal.read_bytes() == journal_before
        assert displaced.exists()
        assert target.read_bytes() == postimage_content
        assert displaced.read_bytes() == preimage_content
        assert subprocess.run(
            ["git", "rev-parse", "HEAD^{commit}"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip() == head_before
        assert subprocess.run(
            ["git", "write-tree"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip() == index_before
        assert file_snapshot(tmp_path / ".git/objects") == git_objects_before
        assert file_snapshot(spec_dir) == spec_before

    @pytest.mark.parametrize(
        "receipt_case",
        (
            "exact_legacy",
            "mixed",
            "unknown_protocol",
            "extra_nested",
            "wrong_type",
            "extra_outer",
        ),
    )
    def test_pending_restore_preflights_receipt_union_before_mutation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        receipt_case: str,
    ) -> None:
        ctrl, store, _current_text = _older_best_proportional_quality_loop(
            tmp_path
        )
        spec_dir = tmp_path / "runs/run-test/specs/001-demo"
        real_materialize = (
            quality_effects_module.materialize_quality_candidate_restore
        )

        def interrupt_before_restore(*_args: object, **_kwargs: object):
            raise KeyboardInterrupt("simulate process death before restore")

        monkeypatch.setattr(
            quality_effects_module,
            "materialize_quality_candidate_restore",
            interrupt_before_restore,
        )
        with pytest.raises(KeyboardInterrupt, match="process death"):
            ctrl.run("prepare receipt discrimination", "semi")
        monkeypatch.setattr(
            quality_effects_module,
            "materialize_quality_candidate_restore",
            real_materialize,
        )

        marker = store.load()[PENDING_CONTROLLER_COMPLETION_KEY]
        prepared = load_prepared_controller_completion(
            tmp_path,
            ctrl._squad_dir,
            marker,
        )
        effect = prepared.intent.quality_effect
        draft = effect["candidate"]
        assert isinstance(draft, dict)
        draft_id = str(draft["candidate_id"])
        candidate_completion_id = hashlib.sha256(
            (
                f"{prepared.intent.completion_id}:quality-candidate"
            ).encode("utf-8")
        ).hexdigest()[:32]
        ledger = json.loads(
            (spec_dir / ".echelon/checkpoints.json").read_text(encoding="utf-8")
        )
        candidate_checkpoint = next(
            row
            for row in ledger["checkpoints"]
            if row.get("completion_id") == candidate_completion_id
        )
        candidate_manifest = (
            ctrl._squad_dir / "quality-candidates" / f"{draft_id}.json"
        )
        candidate_receipt = {
            "schema_version": 1,
            "candidate_id": draft_id,
            "checkpoint": {
                "schema_version": 1,
                "completion_id": candidate_completion_id,
                "run_id": str(effect["run_id"]),
                "spec_id": str(effect["spec_id"]),
                "phase": f"phase1-{draft_id}",
                "next_phase": str(prepared.intent.route["to_phase"]),
                "outcome": "committed",
                "commit": candidate_checkpoint["commit"],
            },
            "manifest_sha256": hashlib.sha256(
                candidate_manifest.read_bytes()
            ).hexdigest(),
        }
        legacy_restore = {
            "schema_version": 1,
            "candidate_id": str(effect["restore_candidate_id"]),
            "artifact_preimage_digests": dict(
                effect["restore_artifact_preimage_digests"]
            ),
            "artifact_postimage_digests": dict(
                json.loads(
                    (
                        ctrl._squad_dir
                        / "quality-candidates"
                        / f"{effect['restore_candidate_id']}.json"
                    ).read_text(encoding="utf-8")
                )["owned_artifact_digests"]
            ),
            "checkpoint": {
                "schema_version": 1,
                "completion_id": "f" * 32,
                "run_id": str(effect["run_id"]),
                "spec_id": str(effect["spec_id"]),
                "phase": "phase1-quality-candidate-restored",
                "next_phase": str(prepared.intent.route["to_phase"]),
                "outcome": "committed",
                "commit": "a" * 40,
            },
        }
        git_restore = {
            **legacy_restore,
            "restore_protocol": "git_first_v1",
            "plan_sha256": "b" * 64,
            "target_commit": "a" * 40,
        }
        restore_receipt: object = git_restore
        outer_extra = False
        if receipt_case == "exact_legacy":
            restore_receipt = legacy_restore
        elif receipt_case == "mixed":
            restore_receipt = {**legacy_restore, "restore_protocol": "git_first_v1"}
        elif receipt_case == "unknown_protocol":
            restore_receipt = {**git_restore, "restore_protocol": "git_first_v2"}
        elif receipt_case == "extra_nested":
            restore_receipt = {**git_restore, "unexpected": True}
        elif receipt_case == "wrong_type":
            restore_receipt = {**git_restore, "plan_sha256": 7}
        else:
            outer_extra = True
            restore_receipt = None
        expected = {
            "schema_version": 1,
            "operation": "candidate",
            "candidate": candidate_receipt,
            "restore": restore_receipt,
        }
        if outer_extra:
            expected["unexpected"] = True

        def file_snapshot(root: Path) -> dict[str, tuple[int, bytes]]:
            return {
                path.relative_to(root).as_posix(): (
                    path.lstat().st_mode,
                    path.read_bytes(),
                )
                for path in root.rglob("*")
                if path.is_file()
            }

        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD^{commit}"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        index_before = subprocess.run(
            ["git", "write-tree"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        git_objects_before = file_snapshot(tmp_path / ".git/objects")
        run_before = file_snapshot(ctrl._squad_dir)
        spec_before = file_snapshot(spec_dir)

        with pytest.raises(CompletionError) as failure:
            quality_effects_module.apply_or_verify_proportional_quality_effect(
                effect,
                completion_id=prepared.intent.completion_id,
                project_root=tmp_path,
                state=store.load(),
                route=prepared.intent.route,
                preceding_checkpoint_receipt=(
                    prepared.receipts["effects"].get("checkpoint")
                ),
                expected_receipt=expected,
            )

        if receipt_case == "exact_legacy":
            assert "legacy candidate restore recovery required" in str(
                failure.value.__cause__
            )
        else:
            assert "receipt" in str(failure.value.__cause__)
        assert subprocess.run(
            ["git", "rev-parse", "HEAD^{commit}"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip() == head_before
        assert subprocess.run(
            ["git", "write-tree"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip() == index_before
        assert file_snapshot(tmp_path / ".git/objects") == git_objects_before
        assert file_snapshot(ctrl._squad_dir) == run_before
        assert file_snapshot(spec_dir) == spec_before

    def test_standalone_restore_rejects_manifest_replacement_before_artifacts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _calls = _run_proportional_quality_loop(
            tmp_path,
            change_what=False,
        )
        real_effect = squad_module.apply_or_verify_proportional_quality_effect
        spec_path = tmp_path / "runs/run-test/specs/001-demo/spec.md"
        source_before = spec_path.read_bytes()
        replaced = False

        def replace_manifest_then_apply(effect: Mapping[str, object], **kwargs: object):
            nonlocal replaced
            if effect.get("operation") == "restore" and not replaced:
                replaced = True
                evidence = store.load()[
                    "proportional_quality_candidate_evidence"
                ]
                manifest = Path(str(evidence["candidate_manifest"]))
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                manifest.write_text(
                    json.dumps(payload, indent=4, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            return real_effect(effect, **kwargs)

        monkeypatch.setattr(
            squad_module,
            "apply_or_verify_proportional_quality_effect",
            replace_manifest_then_apply,
        )

        result = ctrl.run("msg", "semi")

        failed = store.load()
        assert replaced is True
        assert result.status == "blocked"
        assert failed[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == "quality"
        assert failed["controller_completion_failure"]["code"] == (
            "receipts_mismatch"
        )
        assert spec_path.read_bytes() == source_before
        ledger = json.loads(
            (
                spec_path.parent / ".echelon/checkpoints.json"
            ).read_text(encoding="utf-8")
        )
        assert not any(
            row["phase"] == "phase1-quality-candidate-restored"
            for row in ledger["checkpoints"]
        )

    def test_rank_and_restore_seal_the_same_single_manifest_snapshot(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, current_text = _older_best_proportional_quality_loop(
            tmp_path
        )
        selected_manifest = (
            ctrl._squad_dir
            / "quality-candidates/quality-candidate-0.json"
        )
        original_digest = hashlib.sha256(
            selected_manifest.read_bytes()
        ).hexdigest()
        rank = squad_module.rank_quality_candidates
        replaced = False

        def rank_then_replace(candidates: object):
            nonlocal replaced
            ranked = rank(candidates)
            if not replaced:
                replaced = True
                payload = json.loads(
                    selected_manifest.read_text(encoding="utf-8")
                )
                selected_manifest.write_text(
                    json.dumps(payload, indent=4, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            return ranked

        monkeypatch.setattr(
            squad_module,
            "rank_quality_candidates",
            rank_then_replace,
        )

        result = ctrl.run("seal one manifest snapshot", "semi")

        failed = store.load()
        spec_path = tmp_path / "runs/run-test/specs/001-demo/spec.md"
        assert replaced is True
        assert result.status == "blocked"
        assert failed[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == "quality"
        assert failed["controller_completion_failure"]["code"] == (
            "receipts_mismatch"
        )
        assert failed["proportional_quality_candidate_evidence"][
            "candidate_manifest_sha256"
        ] == original_digest
        assert spec_path.read_text(encoding="utf-8") == current_text
        ledger = json.loads(
            (spec_path.parent / ".echelon/checkpoints.json").read_text(
                encoding="utf-8"
            )
        )
        assert not any(
            row["phase"] == "phase1-quality-candidate-restored"
            for row in ledger["checkpoints"]
        )

    def test_candidate_list_slot_rejects_another_candidate_id(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store, _current_text = _older_best_proportional_quality_loop(
            tmp_path
        )
        candidate_dir = ctrl._squad_dir / "quality-candidates"
        (candidate_dir / "quality-candidate-1.json").write_bytes(
            (candidate_dir / "quality-candidate-0.json").read_bytes()
        )
        repair = dict(store.load()["phase1_quality_repair"])
        repair["candidate_ids"] = [
            "quality-candidate-0",
            "quality-candidate-1",
        ]

        with pytest.raises(
            proportional_quality_module.QualityCandidateIntegrityError,
            match="identity mismatch",
        ):
            ctrl._load_proportional_candidate_snapshots(repair)

    def test_combined_restore_authenticates_selected_manifest_before_any_effect(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, current_text = _older_best_proportional_quality_loop(
            tmp_path
        )
        apply_effect = squad_module.apply_or_verify_proportional_quality_effect
        replaced = False
        before_effect: dict[str, object] | None = None
        spec_dir = tmp_path / "runs/run-test/specs/001-demo"

        def capture_mutation_surfaces() -> dict[str, object]:
            candidate_dir = ctrl._squad_dir / "quality-candidates"
            return {
                "head": subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=tmp_path,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
                "new_candidate_manifests": {
                    path.name: path.read_bytes()
                    for path in candidate_dir.glob("quality-candidate-*.json")
                    if path.name != "quality-candidate-0.json"
                },
                "owned_artifacts": {
                    name: (spec_dir / name).read_bytes()
                    for name in (
                        "spec.md",
                        "requirements-overview.md",
                        "quality-gates.md",
                        "issues.md",
                    )
                },
                "checkpoint_ledger": (
                    spec_dir / ".echelon/checkpoints.json"
                ).read_bytes(),
            }

        def replace_manifest_then_apply(
            effect: Mapping[str, object],
            **kwargs: object,
        ):
            nonlocal before_effect, replaced
            if (
                effect.get("operation") == "candidate"
                and effect.get("restore_candidate_id") is not None
                and not replaced
            ):
                replaced = True
                manifest = (
                    ctrl._squad_dir
                    / "quality-candidates/quality-candidate-0.json"
                )
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                manifest.write_text(
                    json.dumps(payload, indent=4, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                before_effect = capture_mutation_surfaces()
            return apply_effect(effect, **kwargs)

        monkeypatch.setattr(
            squad_module,
            "apply_or_verify_proportional_quality_effect",
            replace_manifest_then_apply,
        )

        result = ctrl.run("msg", "semi")

        failed = store.load()
        spec_path = spec_dir / "spec.md"
        assert replaced is True
        assert before_effect is not None
        assert result.status == "blocked"
        assert failed[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == "quality"
        assert failed["controller_completion_failure"]["code"] == (
            "receipts_mismatch"
        )
        assert spec_path.read_text(encoding="utf-8") == current_text
        assert capture_mutation_surfaces() == before_effect

    def test_run_passing_candidate_keeps_routed_and_candidate_checkpoints(
        self,
        tmp_path: Path,
    ) -> None:
        _disable_lexicon_gate(tmp_path)
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-why2",
            max_iterations=10,
            autonomy_mode="semi",
            spec_authoring_mode="proportional",
        )
        _mark_constitution_complete(tmp_path, store)
        state = store.load()
        state.update(
            {
                "spec_id": "001-demo",
                "spec_dir": "runs/run-test/specs/001-demo",
            }
        )
        store.save(state)
        updates, _failure = _proportional_assessment_fixture(ctrl, store, 0)
        evidence = dict(updates["understanding_evidence"])
        report_path = Path(str(evidence["path"]))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["scores"]["overall"] = 0.90
        report["gates"]["overall"].update(
            {
                "score": 0.90,
                "pass": True,
                "numeric_pass": True,
            }
        )
        report["pass"] = True
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
        evidence.update({"digest": digest, "pass": True, "failing_gates": []})
        updates["understanding_evidence"] = evidence
        updates["quality_scores"][-1].update(
            {"pass": True, "overall": 0.90, "evidence_digest": digest}
        )
        _make_authoritative_sage_assessment_passing(ctrl)
        state = store.load()
        state.update(updates)
        store.save(state)
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "PASS",
                "state_updates": {
                    "evidence_resolution_status": "not_required",
                    "finding_routes": {"findings": []},
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        ctrl.run("msg", "semi")

        ledger = json.loads(
            (
                tmp_path
                / "runs/run-test/specs/001-demo/.echelon/checkpoints.json"
            ).read_text(encoding="utf-8")
        )
        routed = [
            row for row in ledger["checkpoints"]
            if row["phase"] == "phase1-why2"
        ]
        candidate = [
            row for row in ledger["checkpoints"]
            if row["phase"] == "phase1-quality-candidate-0"
        ]
        assert len(routed) == 1
        assert len(candidate) == 1
        assert routed[0]["next_phase"] == "checkpoint-assess"
        assert candidate[0]["next_phase"] == "checkpoint-assess"
        assert routed[0]["completion_id"] != candidate[0]["completion_id"]

    def test_run_executes_three_changed_repairs_with_global_iteration_accounting(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store, calls = _run_proportional_quality_loop(tmp_path)

        result = ctrl.run("msg", "semi")

        state = store.load()
        assert result.status == "blocked"
        assert state["blocked_reason"] == "proportional_quality_budget_exhausted"
        assert state["iteration"] == 3
        assert state["phase1_quality_repair"]["automatic_consumed"] == 3
        assert state["phase1_quality_repair"]["candidate_ids"] == [
            "quality-candidate-0",
            "quality-candidate-1",
            "quality-candidate-2",
            "quality-candidate-3",
        ]
        assert calls == {"why2": 4, "what": 3, "understanding": 3}

    def test_run_seals_no_progress_decision_without_the_post_advance_setter(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, calls = _run_proportional_quality_loop(
            tmp_path,
            change_what=False,
        )
        forbidden = MagicMock(
            side_effect=AssertionError("former post-advance decision gap reached")
        )
        monkeypatch.setattr(store, "set_human_input_decision", forbidden)

        result = ctrl.run("msg", "semi")

        state = store.load()
        assert result.status == "blocked"
        assert state["blocked_reason"] == "proportional_quality_budget_exhausted"
        assert state["blocked_decision"]["status"] == "awaiting_human"
        assert state["phase1_quality_repair"]["automatic_consumed"] == 0
        assert calls == {"why2": 1, "what": 1, "understanding": 0}
        forbidden.assert_not_called()

    def test_run_authorizes_and_consumes_single_extension_then_reopens_decision(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store, calls = _run_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )

        initial = ctrl.run("msg", "semi")
        assert initial.status == "blocked"
        assert ctrl.resume_with_human_input("extend_once") is True

        residual = ctrl.run("run the authorized extension", "semi")

        state = store.load()
        assert residual.status == "blocked"
        assert state["blocked_reason"] == (
            "proportional_quality_extension_exhausted"
        )
        assert state["phase1_quality_repair"]["extension_authorized"] == 1
        assert state["phase1_quality_repair"]["extension_consumed"] == 1
        assert state["phase1_quality_repair"]["candidate_ids"] == [
            "quality-candidate-0",
            "quality-candidate-1",
        ]
        assert [
            option["id"] for option in state["blocked_decision"]["options"]
        ] == ["continue_with_debt", "stop"]
        assert calls == {"why2": 2, "what": 1, "understanding": 1}

    @pytest.mark.parametrize("answer", ["continue_with_debt", "stop"])
    def test_run_budget_decision_resolves_debt_or_stop_through_public_path(
        self,
        tmp_path: Path,
        answer: str,
    ) -> None:
        ctrl, store, calls = _run_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        decision = ctrl.run("msg", "semi")
        assert decision.status == "blocked"

        resumed = ctrl.resume_with_human_input(answer)

        state = store.load()
        debt = tmp_path / "runs/run-test/specs/001-demo/quality-debt.json"
        if answer == "continue_with_debt":
            assert resumed is True
            assert debt.is_file()
            assert state["spec_quality_debt_authorization"]["status"] == (
                "accepted_with_debt"
            )
        else:
            assert resumed is False
            assert not debt.exists()
            assert state["blocked_reason"] == (
                "proportional_quality_debt_declined"
            )
        assert PENDING_CONTROLLER_COMPLETION_KEY not in state
        assert calls == {"why2": 1, "what": 0, "understanding": 0}

    def test_banzai_controller_applies_sealed_quality_choice_without_commander(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store, calls = _run_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
            autonomy_mode="banzai",
        )

        result = ctrl.run_single_phase(
            "phase1-why2",
            user_message="resolve exhausted proportional quality",
            mode="banzai",
        )

        state = store.load()
        assert result.status == "running"
        assert state["phase"] == "phase1-lexicon-derive"
        assert state["blocked_decision"]["status"] == "resolved"
        assert state["blocked_decision"]["resolved_by"] == "controller"
        assert state["blocked_decision"]["selected_option_id"] == (
            "continue_with_debt"
        )
        assert state["spec_quality_debt_authorization"]["resolved_by"] == (
            "controller"
        )
        assert (
            tmp_path / "runs/run-test/specs/001-demo/quality-debt.json"
        ).is_file()
        commander_prompts = [
            str(call.args[1])
            for call in ctrl._provider.exec_agent.call_args_list
            if "# COMMANDER DECISION RESOLUTION" in str(call.args[1])
        ]
        assert commander_prompts == []
        assert calls == {"why2": 1, "what": 0, "understanding": 0}

    def test_banzai_ignores_untrusted_commander_answers_for_controller_choice(
        self,
        tmp_path: Path,
    ) -> None:
        undeclared = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DECISION_RESOLVED",
                "state_updates": {},
                "journal_entries": [],
                "decision": {
                    "selected_option_id": "provider_forged_option",
                    "answer_text": None,
                    "rationale": "Attempt an undeclared transition.",
                    "confidence": "high",
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        mutating = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DECISION_RESOLVED",
                "state_updates": {"phase": "phase1-what"},
                "journal_entries": [],
                "decision": {
                    "selected_option_id": "extend_once",
                    "answer_text": None,
                    "rationale": "Attempt to mutate state with a declared choice.",
                    "confidence": "high",
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store, calls = _run_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
            autonomy_mode="banzai",
            commander_results=(undeclared, mutating),
        )

        result = ctrl.run_single_phase(
            "phase1-why2",
            user_message="reject untrusted proportional decisions",
            mode="banzai",
        )

        state = store.load()
        decision = state["blocked_decision"]
        assert result.status == "running"
        assert state["phase"] == "phase1-lexicon-derive"
        assert decision["status"] == "resolved"
        assert decision["resolved_by"] == "controller"
        assert decision["attempts"] == 0
        assert decision["selected_option_id"] == "continue_with_debt"
        assert "spec_quality_debt_authorization" in state
        assert (
            tmp_path / "runs/run-test/specs/001-demo/quality-debt.json"
        ).is_file()
        commander_prompts = [
            str(call.args[1])
            for call in ctrl._provider.exec_agent.call_args_list
            if "# COMMANDER DECISION RESOLUTION" in str(call.args[1])
        ]
        assert commander_prompts == []
        assert [option["id"] for option in decision["options"]] == [
            "extend_once",
            "continue_with_debt",
            "stop",
        ]
        assert calls == {"why2": 1, "what": 0, "understanding": 0}

    def test_manual_replay_replaces_failed_banzai_safeguard_decision(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from echelon.cli import _cmd_phase, _cmd_status

        invalid = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DECISION_RESOLVED",
                "state_updates": {},
                "journal_entries": [],
                "decision": {
                    "selected_option_id": "extend_once",
                    "answer_text": None,
                    "rationale": "r" * 4_097,
                    "confidence": "high",
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        run_dir = tmp_path / "runs/run-test"
        ctrl, store, calls = _run_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
            autonomy_mode="banzai",
            commander_results=(invalid, invalid),
            squad_dir=run_dir,
        )
        (tmp_path / "runs/.current").write_text("run-test\n", encoding="utf-8")
        (tmp_path / ".gitignore").write_text(
            ".echelon/\nruns/\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "add", ".gitignore"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "ignore runtime state"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        shutil.copytree(
            EXT_ROOT / "runtime",
            tmp_path / ".echelon/runtime",
            dirs_exist_ok=True,
        )
        shutil.copytree(
            EXT_ROOT / "prosaic",
            tmp_path / ".echelon/prosaic",
            dirs_exist_ok=True,
        )
        monkeypatch.setattr(
            ctrl,
            "_proportional_controller_resolution",
            lambda _decision, _state: None,
        )

        blocked = ctrl.run_single_phase(
            "phase1-why2",
            user_message="trigger failed automatic decision",
            mode="banzai",
        )
        assert blocked.status == "blocked"
        failed_state = store.load()
        failed = failed_state["blocked_decision"]
        assert failed["status"] == "failed"
        assert failed["failure_code"] == "invalid_resolution_result"
        assert failed_state["phase"] == failed["source_phase"]

        dispatches_before_unarmed_replay = dict(calls)
        provider_calls_before_unarmed_replay = (
            ctrl._provider.exec_agent.call_count
        )
        unarmed = ctrl.run_single_phase(
            "phase1-why2",
            user_message="unarmed replay cannot retire authority",
            mode="banzai",
        )
        assert unarmed.status == "blocked"
        assert calls == dispatches_before_unarmed_replay
        assert ctrl._provider.exec_agent.call_count == (
            provider_calls_before_unarmed_replay
        )
        assert store.load() == failed_state

        _cmd_status(tmp_path)
        status_output = capsys.readouterr().out
        displayed_commands = re.findall(
            r"echelon phase run (?:'[^']*'|\"[^\"]*\"|[A-Za-z0-9_.:-]+)",
            status_output,
        )
        assert displayed_commands == ["echelon phase run phase1-why2"]
        displayed_argv = shlex.split(displayed_commands[0])

        monkeypatch.setattr(
            "harness.squad_provider.SquadCliProvider",
            lambda _config: ctrl._provider,
        )
        _cmd_phase(
            displayed_argv[2:],
            project_root=tmp_path,
            ext_dir=tmp_path / ".echelon/runtime",
        )

        state = store.load()
        assert state["status"] == "running"
        assert state["phase"] == "phase1-lexicon-derive"
        assert state["blocked_decision"]["status"] == "resolved"
        assert state["blocked_decision"]["selected_option_id"] == (
            "continue_with_debt"
        )
        assert state["blocked_decision"]["resolved_by"] == "controller"
        assert calls == {"why2": 2, "what": 0, "understanding": 0}

    def test_failed_proportional_controller_decision_autorecovers_without_replay(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        invalid = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DECISION_RESOLVED",
                "state_updates": {},
                "journal_entries": [],
                "decision": {
                    "selected_option_id": "extend_once",
                    "answer_text": None,
                    "rationale": "r" * 4_097,
                    "confidence": "high",
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store, calls = _run_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
            autonomy_mode="banzai",
            commander_results=(invalid, invalid),
        )
        controller_resolution = ctrl._proportional_controller_resolution
        monkeypatch.setattr(
            ctrl,
            "_proportional_controller_resolution",
            lambda _decision, _state: None,
        )

        blocked = ctrl.run_single_phase(
            "phase1-why2",
            user_message="simulate a pre-fix failed automatic decision",
            mode="banzai",
        )
        assert blocked.status == "blocked"
        assert store.load()["blocked_decision"]["status"] == "failed"
        calls_before_recovery = dict(calls)

        monkeypatch.setattr(
            ctrl,
            "_proportional_controller_resolution",
            controller_resolution,
        )
        assert ctrl.resume_pending_human_input() is True

        recovered = store.load()
        assert recovered["status"] == "running"
        assert recovered["phase"] == "phase1-lexicon-derive"
        assert recovered["blocked_decision"]["status"] == "resolved"
        assert recovered["blocked_decision"]["resolved_by"] == "controller"
        assert recovered["blocked_decision"]["selected_option_id"] == (
            "continue_with_debt"
        )
        assert calls == calls_before_recovery

    def test_run_candidate_capture_cas_failure_has_no_orphan_and_retry_converges(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _calls = _run_proportional_quality_loop(tmp_path)
        real_advance = store.advance
        failed = False

        def fail_first_why2_advance(*args: object, **kwargs: object) -> object:
            nonlocal failed
            if not failed and args and args[0] == "phase1-why2":
                failed = True
                raise StateAdvanceError(
                    "injected candidate authority CAS failure",
                    validator="stale_state",
                )
            return real_advance(*args, **kwargs)

        monkeypatch.setattr(store, "advance", fail_first_why2_advance)

        first = ctrl.run("msg", "semi")

        manifest = (
            ctrl._squad_dir
            / "quality-candidates/quality-candidate-0.json"
        )
        assert first.status == "blocked"
        assert store.load()["phase1_quality_repair"]["candidate_ids"] == []
        assert not manifest.exists()
        assert "phase1-quality-candidate-0" not in subprocess.run(
            ["git", "log", "--format=%B"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

        retried = ctrl.run("msg", "semi")

        assert retried.status == "blocked"
        assert store.load()["phase1_quality_repair"]["candidate_ids"] == [
            "quality-candidate-0",
            "quality-candidate-1",
            "quality-candidate-2",
            "quality-candidate-3",
        ]
        assert manifest.is_file()

    def test_run_candidate_effect_marker_failure_reconciles_without_duplicate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, _calls = _run_proportional_quality_loop(tmp_path)
        real_advance = store.advance_controller_completion
        failed = False

        def fail_after_quality_effect(prepared: object) -> None:
            nonlocal failed
            marker = getattr(prepared, "marker", None)
            if not failed and getattr(marker, "step", None) == "quality":
                failed = True
                raise StateAdvanceError(
                    "injected quality receipt state finalization failure",
                    validator="stale_state",
                )
            real_advance(prepared)

        monkeypatch.setattr(
            store,
            "advance_controller_completion",
            fail_after_quality_effect,
        )

        first = ctrl.run("msg", "semi")

        state = store.load()
        assert failed is True
        assert first.status == "blocked"
        assert state[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == "quality"
        completion_id = state[PENDING_CONTROLLER_COMPLETION_KEY][
            "completion_id"
        ]
        assert state["phase1_quality_repair"]["candidate_ids"] == [
            "quality-candidate-0"
        ]
        assert (
            ctrl._squad_dir
            / "quality-candidates/quality-candidate-0.json"
        ).is_file()

        retried = ctrl.run("msg", "semi")

        assert retried.status == "blocked"
        assert store.load()["blocked_reason"] == (
            "proportional_quality_budget_exhausted"
        )
        log = subprocess.run(
            ["git", "log", "--format=%B"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert log.count("Echelon-Checkpoint: phase1-quality-candidate-0") == 1
        ledger = json.loads(
            (
                tmp_path
                / "runs/run-test/specs/001-demo/.echelon/checkpoints.json"
            ).read_text(encoding="utf-8")
        )
        routed = [
            row for row in ledger["checkpoints"]
            if row["completion_id"] == completion_id
        ]
        candidate_id = hashlib.sha256(
            f"{completion_id}:quality-candidate".encode("utf-8")
        ).hexdigest()[:32]
        candidate = [
            row for row in ledger["checkpoints"]
            if row["completion_id"] == candidate_id
        ]
        assert len(routed) == 1
        assert len(candidate) == 1
        assert routed[0]["next_phase"] == "phase1-what"
        assert candidate[0]["next_phase"] == "phase1-what"

    def test_run_restore_cas_failure_keeps_current_files_then_retry_restores_once(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(tmp_path)
        _mark_constitution_complete(tmp_path, store)
        baseline_updates, why2 = _proportional_assessment_fixture(
            ctrl,
            store,
            0,
            score=0.60,
            spec_text="# Best candidate\n\n- FR-001: Best.\n",
        )
        state = store.load()
        state.update(baseline_updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
        state = store.load()
        repair = dict(state["phase1_quality_repair"])
        repair["automatic_consumed"] = 3
        state.update(
            {
                "phase": "phase1-why2",
                "status": "running",
                "phase1_quality_repair": repair,
            }
        )
        state.pop("blocked_reason", None)
        state.pop("quality_gate_remediation", None)
        store.save(state)
        current_text = "# Worse current candidate\n\n- FR-001: Worse.\n"
        current_updates, _result = _proportional_assessment_fixture(
            ctrl,
            store,
            1,
            score=0.50,
            spec_text=current_text,
        )
        state = store.load()
        state.update(current_updates)
        store.save(state)
        provider = ctrl._provider
        provider.exec_agent.side_effect = None
        provider.exec_agent.return_value = _result
        real_advance = store.advance
        failed = False

        def fail_once(*args: object, **kwargs: object) -> object:
            nonlocal failed
            if not failed:
                failed = True
                raise StateAdvanceError(
                    "injected restore authority CAS failure",
                    validator="stale_state",
                )
            return real_advance(*args, **kwargs)

        monkeypatch.setattr(store, "advance", fail_once)

        first = ctrl.run("msg", "semi")

        spec = tmp_path / "runs/run-test/specs/001-demo/spec.md"
        candidate_one = (
            ctrl._squad_dir
            / "quality-candidates/quality-candidate-1.json"
        )
        assert first.status == "blocked"
        assert spec.read_text(encoding="utf-8") == current_text
        assert not candidate_one.exists()

        retried = ctrl.run("msg", "semi")

        assert retried.status == "blocked"
        assert store.load()["blocked_reason"] == (
            "proportional_quality_budget_exhausted"
        )
        assert spec.read_text(encoding="utf-8").startswith("# Best candidate")
        assert candidate_one.is_file()
        log = subprocess.run(
            ["git", "log", "--format=%B"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert log.count("Echelon-Checkpoint: phase1-quality-candidate-1") == 1

    def test_pending_restore_rejects_direct_resolution_then_resume_reconciles_once(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(tmp_path)
        _mark_constitution_complete(tmp_path, store)
        baseline_updates, baseline = _proportional_assessment_fixture(
            ctrl,
            store,
            0,
            score=0.60,
            spec_text="# Best candidate\n\n- FR-001: Best.\n",
        )
        state = store.load()
        state.update(baseline_updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), baseline)
        state = store.load()
        repair = dict(state["phase1_quality_repair"])
        repair["automatic_consumed"] = 3
        state.update({
            "phase": "phase1-why2",
            "status": "running",
            "phase1_quality_repair": repair,
        })
        state.pop("blocked_reason", None)
        state.pop("quality_gate_remediation", None)
        store.save(state)
        current_updates, current = _proportional_assessment_fixture(
            ctrl,
            store,
            1,
            score=0.50,
            spec_text="# Worse candidate\n\n- FR-001: Worse.\n",
        )
        state = store.load()
        state.update(current_updates)
        store.save(state)
        ctrl._provider.exec_agent.side_effect = None
        ctrl._provider.exec_agent.return_value = current
        real_advance = store.advance_controller_completion
        injected = False

        def fail_after_restore_effect(prepared: object) -> None:
            nonlocal injected
            marker = getattr(prepared, "marker", None)
            if not injected and getattr(marker, "step", None) == "quality":
                injected = True
                raise StateAdvanceError(
                    "injected restored receipt finalization failure",
                    validator="stale_state",
                )
            real_advance(prepared)

        monkeypatch.setattr(
            store,
            "advance_controller_completion",
            fail_after_restore_effect,
        )

        first = ctrl.run("msg", "semi")

        spec = tmp_path / "runs/run-test/specs/001-demo/spec.md"
        pending = store.load()
        assert injected is True
        assert first.status == "blocked"
        assert pending[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == "quality"
        completion_id = pending[PENDING_CONTROLLER_COMPLETION_KEY][
            "completion_id"
        ]
        outbox_receipts = json.loads(
            (
                ctrl._squad_dir
                / ".completion-outbox"
                / completion_id
                / "receipts.json"
            ).read_text(encoding="utf-8")
        )
        restore_receipt = outbox_receipts["effects"]["quality"]["restore"]
        assert outbox_receipts["schema_version"] == 1
        assert restore_receipt["restore_protocol"] == "git_first_v1"
        assert restore_receipt["target_commit"] == (
            restore_receipt["checkpoint"]["commit"]
        )
        assert re.fullmatch(r"[0-9a-f]{64}", restore_receipt["plan_sha256"])
        assert spec.read_text(encoding="utf-8").startswith("# Best candidate")
        calls = ctrl._provider.exec_agent.call_count
        decision = pending["blocked_decision"]
        with pytest.raises(HumanInputPolicyError, match="completion.*pending"):
            ctrl.apply_human_input_resolution(
                decision["id"],
                expected_state_revision=pending["state_revision"],
                resolution=HumanInputResolution(
                    selected_option_id="extend_once",
                    answer_text=None,
                    resolved_by="user",
                ),
            )
        after_rejected = store.load()
        assert after_rejected == pending
        assert after_rejected["phase1_quality_repair"][
            "extension_authorized"
        ] == 0
        assert after_rejected["blocked_decision"]["status"] == "awaiting_human"

        reconciled = ctrl.run("reconcile the pending restore", "semi")

        after_reconcile = store.load()
        assert reconciled.status == "blocked"
        assert PENDING_CONTROLLER_COMPLETION_KEY not in after_reconcile
        assert after_reconcile["phase1_quality_repair"][
            "extension_authorized"
        ] == 0
        assert after_reconcile["blocked_decision"]["status"] == "awaiting_human"
        assert ctrl._provider.exec_agent.call_count == calls

        assert ctrl.resume_with_human_input("extend_once") is True

        assert ctrl._provider.exec_agent.call_count == calls
        resolved = store.load()
        assert PENDING_CONTROLLER_COMPLETION_KEY not in resolved
        assert resolved["phase"] == "phase1-what"
        assert resolved["phase1_quality_repair"]["extension_authorized"] == 1
        assert resolved["blocked_decision"]["status"] == "resolved"
        log = subprocess.run(
            ["git", "log", "--format=%B"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert log.count("Echelon-Checkpoint: phase1-quality-candidate-restored") == 1
        ledger = json.loads(
            (
                tmp_path
                / "runs/run-test/specs/001-demo/.echelon/checkpoints.json"
            ).read_text(encoding="utf-8")
        )
        routed = [
            row for row in ledger["checkpoints"]
            if row["completion_id"] == completion_id
        ]
        restore_id = hashlib.sha256(
            f"{completion_id}:quality-restore".encode("utf-8")
        ).hexdigest()[:32]
        restored = [
            row for row in ledger["checkpoints"]
            if row["completion_id"] == restore_id
        ]
        assert len(routed) == 1
        assert len(restored) == 1
        assert routed[0]["next_phase"] == "terminal-blocked"
        assert restored[0]["next_phase"] == "terminal-blocked"
        assert routed[0]["completion_id"] != restored[0]["completion_id"]

    @pytest.mark.parametrize(
        ("severity", "issue_type"),
        [
            ("CRITICAL", "incompleteness"),
            ("LOW", "contradiction"),
        ],
    )
    def test_authoritative_issue_artifact_forbids_quality_debt(
        self,
        tmp_path: Path,
        severity: str,
        issue_type: str,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        issues = tmp_path / "runs/run-test/specs/001-demo/issues.md"
        content = issues.read_text(encoding="utf-8")
        content = content.replace(
            "- **CRITICAL:** 0",
            f"- **CRITICAL:** {1 if severity == 'CRITICAL' else 0}",
        ).replace(
            "- **LOW:** 1",
            f"- **LOW:** {0 if severity == 'CRITICAL' else 1}",
        ).replace("- **Severity:** LOW", f"- **Severity:** {severity}").replace(
            "- **Type:** incompleteness",
            f"- **Type:** {issue_type}",
        )
        issues.write_text(content, encoding="utf-8")
        state = store.load()
        state.update(updates)
        store.save(state)

        next_phase = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            why2,
        )

        persisted = store.load()
        assert next_phase == "terminal-blocked"
        assert persisted["blocked_reason"] == (
            "proportional_quality_candidate_integrity_failed"
        )
        assert "blocked_decision" not in persisted
        assert "spec_quality_debt_authorization" not in persisted
        assert persisted["phase1_quality_repair"]["candidate_ids"] == []

    def test_malformed_authoritative_issue_artifact_fails_closed_without_debt(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        (tmp_path / "runs/run-test/specs/001-demo/issues.md").write_text(
            "# malformed issues without authoritative summary\n",
            encoding="utf-8",
        )
        state = store.load()
        state.update(updates)
        store.save(state)

        next_phase = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            why2,
        )

        persisted = store.load()
        assert next_phase == "terminal-blocked"
        assert persisted["blocked_reason"] == (
            "proportional_quality_candidate_integrity_failed"
        )
        assert "blocked_decision" not in persisted
        assert "spec_quality_debt_authorization" not in persisted

    def test_debt_resolution_cas_failure_writes_nothing_and_retry_converges(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
        real_apply = store.apply_human_input_state_resolution
        failed = False

        def fail_once(*args: object, **kwargs: object) -> object:
            nonlocal failed
            if not failed:
                failed = True
                raise StateAdvanceError(
                    "injected debt resolution CAS failure",
                    validator="stale_state",
                )
            return real_apply(*args, **kwargs)

        monkeypatch.setattr(
            store,
            "apply_human_input_state_resolution",
            fail_once,
        )
        debt_path = tmp_path / "runs/run-test/specs/001-demo/quality-debt.json"

        with pytest.raises(StateAdvanceError, match="injected debt"):
            ctrl.resume_with_human_input("continue_with_debt")

        assert not debt_path.exists()
        assert store.load()["blocked_decision"]["status"] == "awaiting_human"
        assert "spec_quality_debt_authorization" not in store.load()

        assert ctrl.resume_with_human_input("continue_with_debt")
        assert debt_path.is_file()
        assert store.load()["spec_quality_debt_authorization"]["status"] == (
            "accepted_with_debt"
        )

    def test_debt_write_failure_stays_pending_and_retry_reconciles_before_dispatch(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
        real_effect = getattr(
            squad_module,
            "apply_or_verify_proportional_quality_effect",
            None,
        )
        effect_calls = 0

        def fail_effect(*args: object, **kwargs: object) -> object:
            nonlocal effect_calls
            effect_calls += 1
            raise CompletionError("stage_io")

        monkeypatch.setattr(
            squad_module,
            "apply_or_verify_proportional_quality_effect",
            fail_effect,
            raising=False,
        )
        provider_calls = ctrl._provider.exec_agent.call_count

        assert ctrl.resume_with_human_input("continue_with_debt") is False

        debt_path = tmp_path / "runs/run-test/specs/001-demo/quality-debt.json"
        pending = store.load()
        assert not debt_path.exists()
        assert PENDING_CONTROLLER_COMPLETION_KEY in pending
        assert pending["blocked_reason"] == "controller_completion_pending"
        ctrl.run("must reconcile before downstream", "semi")
        assert ctrl._provider.exec_agent.call_count == provider_calls
        assert effect_calls >= 2

        assert real_effect is not None
        monkeypatch.setattr(
            squad_module,
            "apply_or_verify_proportional_quality_effect",
            real_effect,
        )
        recovered = ctrl._drain_pending_controller_completion()
        assert recovered.recovered is True
        assert debt_path.is_file()
        assert PENDING_CONTROLLER_COMPLETION_KEY not in store.load()

    def test_stop_removes_stale_debt_artifact_through_recoverable_effect(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
        debt_path = tmp_path / "runs/run-test/specs/001-demo/quality-debt.json"
        debt_path.write_text('{"stale":true}\n', encoding="utf-8")

        assert ctrl.resume_with_human_input("stop") is False

        stopped = store.load()
        assert stopped["blocked_reason"] == "proportional_quality_debt_declined"
        assert not debt_path.exists()
        assert "spec_quality_debt_authorization" not in stopped
        assert PENDING_CONTROLLER_COMPLETION_KEY not in stopped


    @pytest.mark.parametrize(
        ("failure_kind", "expected_reason"),
        [
            ("timeout", "agent_timeout"),
            ("provider_error", "agent_exit_code_7"),
            (
                "missing_envelope",
                "controller_state_contract_validation_failed",
            ),
            ("invalid_mandatory_artifact", "missing_phase_outputs"),
            (
                "state_contract",
                "controller_state_contract_validation_failed",
            ),
            (
                "debt_state_contract",
                "controller_state_contract_validation_failed",
            ),
        ],
    )
    def test_operational_what_failures_leave_extension_recoverable(
        self,
        tmp_path: Path,
        failure_kind: str,
        expected_reason: str,
    ) -> None:
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
            max_iterations=10,
            autonomy_mode="banzai",
            spec_authoring_mode="proportional",
        )
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "runs/run-test/specs/001-demo"
        spec_dir.mkdir(parents=True)
        spec = spec_dir / "spec.md"
        spec.write_text("# Extension candidate\n", encoding="utf-8")
        if failure_kind != "invalid_mandatory_artifact":
            (spec_dir / "requirements-overview.md").write_text(
                "# Overview\n",
                encoding="utf-8",
            )
        state = store.load()
        repair = dict(state["phase1_quality_repair"])
        repair.update(
            {
                "automatic_consumed": 3,
                "extension_authorized": 1,
                "extension_consumed": 0,
            }
        )
        state.update(
            {
                "spec_id": "001-demo",
                "spec_dir": "runs/run-test/specs/001-demo",
                "phase1_quality_repair": repair,
                "quality_gate_remediation": {
                    "kind": "proportional_quality",
                    "baseline_spec_sha256": hashlib.sha256(
                        spec.read_bytes()
                    ).hexdigest(),
                    "extension_active": True,
                },
            }
        )
        store.save(state)
        valid_payload: dict[str, object] | None = {
            "verdict": "DONE",
            "output_files": [
                str(spec),
                str(spec_dir / "requirements-overview.md"),
            ],
            "state_updates": {
                "evidence_resolution_status": "not_required",
            },
        }
        exit_code = 0
        timed_out = False
        if failure_kind == "timeout":
            timed_out = True
        elif failure_kind == "provider_error":
            exit_code = 7
        elif failure_kind == "missing_envelope":
            valid_payload = None
        elif failure_kind == "state_contract":
            assert valid_payload is not None
            valid_payload["state_updates"] = {
                "evidence_resolution_status": "not_required",
                "phase1_quality_repair": {"forged": True},
            }
        elif failure_kind == "debt_state_contract":
            assert valid_payload is not None
            valid_payload["state_updates"] = {
                "evidence_resolution_status": "not_required",
                "spec_quality_debt_authorization": {"forged": True},
            }
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=exit_code,
            echelon_result=valid_payload,
            raw_output="operational failure",
            duration_ms=1,
            timed_out=timed_out,
        )
        before = dict(repair)

        result = ctrl.run("msg", "banzai")

        blocked = store.load()
        assert result.status == "blocked"
        assert blocked["blocked_reason"] == expected_reason
        assert blocked["phase1_quality_repair"] == before
        assert "blocked_decision" not in blocked
        assert "spec_quality_debt_authorization" not in blocked
        assert not (spec_dir / "quality-debt.json").exists()

    def test_initial_assessment_and_three_changed_repairs_restore_best_candidate(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(tmp_path)
        retained_candidate = PROPORTIONAL_HELLO_WORLD_FIXTURE.read_text(
            encoding="utf-8"
        )
        initial_updates, why2 = _proportional_assessment_fixture(
            ctrl,
            store,
            0,
            spec_text=retained_candidate,
            requirement_count=13,
        )
        state = store.load()
        state.update(initial_updates)
        store.save(state)

        assert (
            _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
            == "phase1-what"
        )
        repair = store.load()["phase1_quality_repair"]
        assert repair["automatic_consumed"] == 0
        assert repair["candidate_ids"] == ["quality-candidate-0"]

        routes: list[str] = []
        for assessment_index in range(1, 4):
            spec = (
                f"# Candidate {assessment_index}\n\n"
                + "".join(
                    f"- FR-{statement:03d}: The system shall render revision "
                    f"{assessment_index}, statement {statement}.\n"
                    for statement in range(1, assessment_index + 14)
                )
            )
            assessment_updates, why2 = _proportional_assessment_fixture(
                ctrl,
                store,
                assessment_index,
                score=0.60,
                spec_text=spec,
                requirement_count=assessment_index + 13,
            )
            routes.append(
                _coordinate_prepared_result(
                    ctrl,
                    ctrl._graph.get("phase1-what"),
                    SquadAgentResult(
                        exit_code=0,
                        echelon_result={
                            "verdict": "DONE",
                            "state_updates": {
                                "evidence_resolution_status": "not_required",
                            },
                        },
                        raw_output="",
                        duration_ms=0,
                        timed_out=False,
                    ),
                )
            )
            assert store.load()["phase1_quality_repair"][
                "automatic_consumed"
            ] == assessment_index
            routes.append(
                _route_understanding_assessment(ctrl, store, assessment_updates)
            )
            routes.append(
                _coordinate_prepared_result(
                    ctrl,
                    ctrl._graph.get("phase1-why2"),
                    why2,
                )
            )

        assert routes[:8] == [
            "phase1-understanding",
            "phase1-why2",
            "phase1-what",
            "phase1-understanding",
            "phase1-why2",
            "phase1-what",
            "phase1-understanding",
            "phase1-why2",
        ]
        assert routes[-1] == "terminal-blocked"
        blocked = store.load()
        assert blocked["phase1_quality_repair"]["candidate_ids"] == [
            "quality-candidate-0",
            "quality-candidate-1",
            "quality-candidate-2",
            "quality-candidate-3",
        ]
        assert blocked["blocked_reason"] == (
            "proportional_quality_budget_exhausted"
        )
        assert blocked["blocked_decision"]["reason_code"] == (
            "proportional_quality_budget_exhausted"
        )
        assert blocked["blocked_decision"]["status"] == "awaiting_human"
        assert [
            option["id"] for option in blocked["blocked_decision"]["options"]
        ] == ["extend_once", "continue_with_debt", "stop"]
        assert "spec_quality_certificate" not in blocked
        recommendation = blocked["proportional_quality_candidate_evidence"][
            "recommendation_evidence"
        ]
        assert recommendation["baseline_candidate_id"] == "quality-candidate-0"
        assert recommendation["current_candidate_id"] == "quality-candidate-3"
        baseline_manifest = json.loads(
            (
                ctrl._squad_dir
                / "quality-candidates"
                / "quality-candidate-0.json"
            ).read_text(encoding="utf-8")
        )
        current_manifest = json.loads(
            (
                ctrl._squad_dir
                / "quality-candidates"
                / "quality-candidate-3.json"
            ).read_text(encoding="utf-8")
        )
        assert current_manifest["sage_finding_routes"][0]["issue_id"] == (
            "ISS-QUALITY-3"
        )
        assert current_manifest["sage_finding_routes"][0]["type"] == (
            "incompleteness"
        )
        assert recommendation["baseline_formal_statement_count"] == 13
        assert recommendation["formal_statement_count"] == 16
        assert recommendation["formal_statement_growth"] == 3
        assert recommendation["baseline_byte_count"] == baseline_manifest["byte_count"]
        assert recommendation["byte_count"] == current_manifest["byte_count"]
        assert recommendation["byte_growth"] == (
            current_manifest["byte_count"] - baseline_manifest["byte_count"]
        )
        assert recommendation["recommended_option_id"] in {
            "extend_once",
            "continue_with_debt",
        }
        assert type(recommendation["formal_statement_growth"]) is int
        assert type(recommendation["byte_growth"]) is int
        assert recommendation["rationale"]
        assert blocked.get("why2_metric_stagnation_count", 0) == 0
        assert (tmp_path / "runs/run-test/specs/001-demo/spec.md").read_text(
            encoding="utf-8"
        ) == retained_candidate

    def test_valid_unchanged_automatic_what_opens_no_progress_decision(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(tmp_path)
        initial_updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(initial_updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)

        next_phase = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-what"),
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {
                        "evidence_resolution_status": "not_required",
                    },
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            ),
        )

        assert next_phase == "phase1-why2"
        blocked = store.load()
        assert blocked["phase1_quality_repair"]["automatic_consumed"] == 0
        assert blocked["blocked_reason"] == (
            "proportional_quality_budget_exhausted"
        )
        assert blocked["proportional_quality_candidate_evidence"][
            "last_repair_outcome"
        ] == "no_artifact_progress"
        assert blocked["blocked_decision"]["status"] == "awaiting_human"

    def test_extension_is_authorized_and_consumed_once_even_when_unchanged(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        initial_updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(initial_updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
        budget = store.load()
        first_decision_id = budget["blocked_decision"]["id"]

        assert ctrl.resume_with_human_input("extend_once")
        authorized = store.load()
        assert authorized["phase"] == "phase1-what"
        assert authorized["phase1_quality_repair"]["extension_authorized"] == 1
        assert authorized["phase1_quality_repair"]["extension_consumed"] == 0

        assert (
            _coordinate_prepared_result(
                ctrl,
                ctrl._graph.get("phase1-what"),
                SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "DONE",
                        "state_updates": {
                            "evidence_resolution_status": "not_required",
                        },
                    },
                    raw_output="",
                    duration_ms=0,
                    timed_out=False,
                ),
            )
            == "phase1-understanding"
        )
        assert store.load()["phase1_quality_repair"]["extension_consumed"] == 1

        extension_updates, why2 = _proportional_assessment_fixture(
            ctrl,
            store,
            1,
            spec_text=(
                tmp_path / "runs/run-test/specs/001-demo/spec.md"
            ).read_text(encoding="utf-8"),
        )
        assert (
            _route_understanding_assessment(ctrl, store, extension_updates)
            == "phase1-why2"
        )
        assert (
            _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
            == "terminal-blocked"
        )
        exhausted = store.load()
        assert exhausted["blocked_reason"] == (
            "proportional_quality_extension_exhausted"
        )
        assert [
            option["id"] for option in exhausted["blocked_decision"]["options"]
        ] == ["continue_with_debt", "stop"]
        with pytest.raises(HumanInputPolicyError):
            ctrl.apply_human_input_resolution(
                first_decision_id,
                expected_state_revision=exhausted["state_revision"],
                resolution=HumanInputResolution(
                    selected_option_id="extend_once",
                    answer_text=None,
                    resolved_by="user",
                ),
            )
        assert store.load()["phase1_quality_repair"]["extension_authorized"] == 1

    @pytest.mark.parametrize("lexicon_enabled", [True, False])
    def test_continue_with_debt_builds_authorization_and_routes_conditionally(
        self,
        tmp_path: Path,
        lexicon_enabled: bool,
    ) -> None:
        if not lexicon_enabled:
            _disable_lexicon_gate(tmp_path)
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        initial_updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(initial_updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
        sealed_id = store.load()["blocked_decision"]["id"]

        assert ctrl.resume_with_human_input("continue_with_debt")

        accepted = store.load()
        assert accepted["phase"] == (
            "phase1-lexicon-derive" if lexicon_enabled else "checkpoint-assess"
        )
        authorization = accepted["spec_quality_debt_authorization"]
        assert authorization["decision_id"] == sealed_id
        assert authorization["resolved_by"] == "user"
        assert authorization["status"] == "accepted_with_debt"
        assert "spec_quality_certificate" not in accepted
        assert (
            tmp_path
            / "runs/run-test/specs/001-demo/quality-debt.json"
        ).is_file()

    def test_stop_is_durable_and_ordinary_continue_cannot_reopen_it(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        initial_updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(initial_updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)

        assert ctrl.resume_with_human_input("stop") is False
        declined = store.load()
        assert declined["blocked_reason"] == (
            "proportional_quality_debt_declined"
        )
        assert declined["blocked_decision"]["status"] == "resolved"
        assert "spec_quality_debt_authorization" not in declined

        result = ctrl.run("ordinary continue", "semi", "phase1-what")

        assert result.status == "blocked"
        assert store.load()["blocked_reason"] == (
            "proportional_quality_debt_declined"
        )
        assert store.load()["phase1_quality_repair"] == declined[
            "phase1_quality_repair"
        ]

    def test_passing_assessment_still_captures_candidate_zero(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(tmp_path)
        updates, _failure = _proportional_assessment_fixture(ctrl, store, 0)
        evidence = dict(updates["understanding_evidence"])
        report_path = Path(str(evidence["path"]))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["scores"]["overall"] = 0.90
        report["gates"]["overall"].update(
            {
                "score": 0.90,
                "pass": True,
                "numeric_pass": True,
            }
        )
        report["pass"] = True
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
        evidence.update(
            {
                "digest": digest,
                "pass": True,
                "failing_gates": [],
            }
        )
        updates["understanding_evidence"] = evidence
        updates["quality_scores"][-1].update(
            {
                "pass": True,
                "overall": 0.90,
                "evidence_digest": digest,
            }
        )
        _make_authoritative_sage_assessment_passing(ctrl)
        state = store.load()
        state.update(updates)
        store.save(state)

        _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-why2"),
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "PASS",
                    "state_updates": {
                        "evidence_resolution_status": "not_required",
                        "finding_routes": {"findings": []},
                    },
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            ),
        )

        persisted = store.load()
        assert persisted["phase1_quality_repair"]["automatic_consumed"] == 0
        assert persisted["phase1_quality_repair"]["candidate_ids"] == [
            "quality-candidate-0"
        ]
        assert persisted["spec_quality_certificate"]["schema_version"] == 2
        assert persisted["spec_quality_certificate"]["sage_verdict"] == "PASS"

    def test_perfectionist_why2_failure_keeps_legacy_route(self, tmp_path: Path) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-why2",
            max_iterations=5,
            autonomy_mode="semi",
            spec_authoring_mode="perfectionist",
        )
        state = store.load()
        state["quality_scores"] = [{"pass": False}]
        store.save(state)

        assert (
            _coordinate_prepared_result(
                ctrl,
                ctrl._graph.get("phase1-why2"),
                SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "FAIL",
                        "state_updates": {
                            "evidence_resolution_status": "not_required",
                            "finding_routes": {
                                "findings": [
                                    {
                                        "issue_id": "ISS-LEGACY",
                                        "route": "spec_repair",
                                        "rationale": "Legacy quality repair is required.",
                                    }
                                ]
                            },
                        },
                    },
                    raw_output="",
                    duration_ms=0,
                    timed_out=False,
                ),
            )
            == "phase1-what"
        )
        persisted = store.load()
        assert persisted["iteration"] == 1
        assert "phase1_quality_repair" not in persisted
        assert "proportional_quality_candidate_evidence" not in persisted


class TestHumanGateControllerInterception:
    class _ExecutorLookupForbidden:
        def get(self, phase_type):
            raise AssertionError(
                f"executor lookup reached for intercepted {phase_type!r}"
            )

    @staticmethod
    def _at_plan_gate(tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider, mode="guided")
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "checkpoint-plan",
            autonomy_mode="guided",
        )
        _mark_constitution_complete(tmp_path, store)
        ctrl._guard_spec_lexicon_evidence = lambda phase: phase
        ctrl._guard_phase1_quality_evidence = lambda phase: phase
        ctrl._guard_understanding_evidence = lambda phase: phase
        ctrl._executors = (
            TestHumanGateControllerInterception._ExecutorLookupForbidden()
        )
        return ctrl, store, provider

    def test_run_intercepts_gate_before_executor_lookup(self, tmp_path):
        ctrl, store, provider = self._at_plan_gate(tmp_path)

        result = ctrl.run("msg", "guided")

        state = store.load()
        assert result.status == "blocked"
        assert state["phase"] == "checkpoint-plan"
        assert state["blocked_decision"]["status"] == "awaiting_human"
        assert "human_input_outcome" not in state
        provider.exec_agent.assert_not_called()

    def test_run_single_phase_intercepts_gate_before_executor_lookup(self, tmp_path):
        ctrl, store, provider = self._at_plan_gate(tmp_path)

        result = ctrl.run_single_phase(
            "checkpoint-plan",
            user_message="msg",
            mode="guided",
        )

        state = store.load()
        assert result.status == "blocked"
        assert state["phase"] == "checkpoint-plan"
        assert state["blocked_decision"]["status"] == "awaiting_human"
        assert "human_input_outcome" not in state
        provider.exec_agent.assert_not_called()


@pytest.mark.parametrize(
    ("mode", "expected_status", "expected_resolver", "provider_calls"),
    [
        ("guided", "awaiting_human", None, 1),
        ("semi", "awaiting_human", None, 1),
        ("banzai", "awaiting_human", None, 1),
    ],
)
def test_run_single_phase_routes_new_provider_question_through_shared_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_status: str,
    expected_resolver: str | None,
    provider_calls: int,
) -> None:
    provider_question = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "STOP_AND_ASK",
            "state_updates": {
                "status": "blocked",
                "blocked_reason": "human_clarification_required",
                "escalation_question": (
                    "Which bounded product constraint should TRACKER record?"
                ),
            },
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=1,
        timed_out=False,
    )
    commander_answer = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DECISION_RESOLVED",
            "state_updates": {},
            "journal_entries": [],
            "decision": {
                "selected_option_id": None,
                "answer_text": "Use the public product boundary.",
                "rationale": "The declared boundary is the best allowed answer.",
                "confidence": "high",
            },
        },
        raw_output="",
        duration_ms=1,
        timed_out=False,
    )
    provider = MagicMock()
    provider.exec_agent.side_effect = (
        [provider_question, commander_answer]
        if mode == "banzai"
        else [provider_question]
    )
    ctrl, store = _controller(tmp_path, provider=provider)
    monkeypatch.setattr(ctrl, "_refresh_run_context", lambda _reason: None)

    result = ctrl.run_single_phase(
        "phase1-tracker",
        user_message="record the product boundary",
        mode=mode,
    )

    state = store.load()
    decision = state["blocked_decision"]
    assert decision["source_kind"] == "provider_escalation"
    assert decision["producer_id"] == "phase1-tracker"
    assert decision["status"] == expected_status
    assert decision["resolved_by"] == expected_resolver
    assert provider.exec_agent.call_count == provider_calls
    assert result.status == (
        "running" if expected_status == "resolved" else "blocked"
    )


def test_invalid_provider_answer_shape_uses_redacted_controller_failure_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "SECRET-PROVIDER-QUESTION-MUST-NOT-PERSIST"
    invalid_question = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "STOP_AND_ASK",
            "state_updates": {
                "status": "blocked",
                "blocked_reason": "human_clarification_required",
                "escalation_question": secret,
                "escalation_options": [
                    {
                        "id": "retry",
                        "label": "Retry",
                        "description": "Retry with bounded evidence.",
                        "recommended": False,
                        "risk_level": "medium",
                        "next_phase": "phase1-tracker",
                    }
                ],
                "escalation_recommended_answer": (
                    "A conflicting free-text recommendation."
                ),
                "escalation_risk_level": "medium",
            },
            "journal_entries": [],
        },
        raw_output="",
        duration_ms=1,
        timed_out=False,
    )
    provider = MagicMock()
    provider.exec_agent.return_value = invalid_question
    ctrl, store = _controller(tmp_path, provider=provider)
    monkeypatch.setattr(ctrl, "_refresh_run_context", lambda _reason: None)

    result = ctrl.run_single_phase(
        "phase1-tracker",
        user_message="record the product boundary",
        mode="banzai",
    )

    state = store.load()
    assert result.status == "blocked"
    assert state["blocked_reason"] == (
        "controller_state_contract_validation_failed"
    )
    assert state["controller_contract_error"]["validator"] == (
        "human_input_policy_invalid"
    )
    assert secret not in json.dumps(state)
    assert "blocked_decision" not in state
    assert "escalation_question" not in state
    assert provider.exec_agent.call_count == 1


def test_run_single_phase_rejects_provider_and_safeguard_question_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _mock_provider("ALIGNED")
    ctrl, store = _controller(tmp_path, provider=provider)
    store.initialize(
        "r",
        "greenfield",
        "msg",
        0,
        "phase1-tracker",
        autonomy_mode="guided",
    )
    monkeypatch.setattr(ctrl, "_refresh_run_context", lambda _reason: None)
    snapshot = store.capture_routing_snapshot(
        expected_phase="phase1-tracker"
    )
    provider_request = ctrl._human_input_registry.prepare(
        source_kind="provider_escalation",
        producer_id="phase1-tracker",
        phase_id="phase1-tracker",
        reason_code="human_clarification_required",
        question="Provider question.",
        source_state_revision=snapshot.state_revision,
    )
    safeguard_policy = ctrl._human_input_registry.lookup(
        "controller_safeguard",
        "consecutive_why_fails",
        "consecutive_why_fails",
    )
    safeguard_request = ctrl._human_input_registry.prepare(
        source_kind=safeguard_policy.source_kind,
        producer_id=safeguard_policy.producer_id,
        phase_id="phase1-why2",
        reason_code=safeguard_policy.reason_code,
        question="Safeguard question.",
        source_state_revision=snapshot.state_revision,
    )
    decision = MagicMock()
    decision.from_phase = "phase1-tracker"
    decision.to_phase = "phase1-tracker"
    decision.token_usage_delta = 0
    ctrl._construct_routing_decision_or_block = MagicMock(
        return_value=SimpleNamespace(
            decision=decision,
            human_input=safeguard_request,
        )
    )
    ctrl._prepare_provider_human_input = MagicMock(
        return_value=provider_request
    )
    ctrl._block_after_state_advance_failure = MagicMock()
    ctrl.handle_human_input = MagicMock()

    ctrl.run_single_phase(
        "phase1-tracker",
        user_message="msg",
        mode="guided",
    )

    ctrl._prepare_provider_human_input.assert_called_once()
    ctrl._block_after_state_advance_failure.assert_called_once()
    ctrl.handle_human_input.assert_not_called()


class TestConvergenceRoutingGuard:
    def test_forced_convergence_skips_why2_dispatch(self, tmp_path):
        _disable_governance_gate(tmp_path)
        _disable_lexicon_gate(tmp_path)
        provider = _mock_provider("KILL")
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-why2", max_iterations=5)
        state = store.load()
        state.update({
            "convergence_forced": True,
            "convergence_detected": True,
            "phase_recommendation": "phase2-decide",
            "why_fail_count": 13,
        })
        store.save(state)
        _mark_constitution_complete(tmp_path, store)

        result = ctrl.run("msg", "banzai")

        assert result.status == "done"
        assert (
            store.load()["last_dispatch"]["phase_id"]
            == "phase2-feasibility-structural"
        )
        assert provider.exec_agent.call_count == 1

    def test_blocked_empty_escalation_with_convergence_recovers_to_recommendation(self, tmp_path):
        _disable_governance_gate(tmp_path)
        _disable_lexicon_gate(tmp_path)
        provider = _mock_provider("KILL")
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-what", max_iterations=5)
        state = store.load()
        state.update({
            "status": "blocked",
            "blocked_reason": "consecutive_why_fails",
            "escalation_question": "",
            "convergence_forced": True,
            "phase_recommendation": "phase2-decide",
        })
        store.save(state)
        _mark_constitution_complete(tmp_path, store)

        result = ctrl.run("msg", "banzai")

        assert result.status == "done"
        assert (
            store.load()["last_dispatch"]["phase_id"]
            == "phase2-feasibility-structural"
        )
        assert provider.exec_agent.call_count == 1


class TestConsensusAcceptWithRiskRouting:
    def test_accept_with_risk_cannot_override_sage_qualitative_failure(self, tmp_path):
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-consensus", max_iterations=10)
        state = store.load()
        state.update(
            {
                "iteration": 9,
                "why3_verdict": "FAIL",
                "assess2_verdict": "PASS",
                "gate_decision": "accept_with_risk",
                "phase_recommendation": "advance_past_consensus_to_delivery",
                "quality_scores": [
                    {"pass": True, "source": "harness:understanding"}
                ],
            }
        )
        store.save(state)

        consensus_result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "PASS", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        assert _evaluate_prepared_result(ctrl,
            ctrl._graph.get("phase3-consensus"), consensus_result
        ) == "phase3-consensus-tasks-lexicon"
        gate = ctrl._graph.get("phase3-consensus-tasks-lexicon")
        gate_result = ctrl._executors["deterministic_lexicon"].execute(gate, store)
        assert _evaluate_prepared_result(ctrl, gate, gate_result) == "phase1-what"

    def test_accept_with_risk_can_override_feasibility_rejection_only(self, tmp_path):
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-consensus", max_iterations=10)
        state = store.load()
        state.update(
            {
                "iteration": 9,
                "why3_verdict": "PASS",
                "assess2_verdict": "REJECTED",
                "gate_decision": "accept_with_risk",
                "quality_scores": [
                    {"pass": True, "source": "harness:understanding"}
                ],
            }
        )
        store.save(state)

        consensus_result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "PASS", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        assert _evaluate_prepared_result(ctrl,
            ctrl._graph.get("phase3-consensus"), consensus_result
        ) == "phase3-consensus-tasks-lexicon"
        gate = ctrl._graph.get("phase3-consensus-tasks-lexicon")
        gate_result = ctrl._executors["deterministic_lexicon"].execute(gate, store)
        assert _evaluate_prepared_result(ctrl, gate, gate_result) == "checkpoint-plan"


class TestBuildPhaseRouting:
    """Regression: 12 build-phase transition conditions used lowercase 'and'
    (e.g. 'verdict = FAIL and fix_cycle < 2'). The evaluator splits only on
    uppercase AND/OR, so every compound was treated as a single field=value
    match that always returned False — fix-cycle routing was silently broken.

    Each test starts SquadController at the relevant build phase, injects the
    appropriate initial state (fix_cycle, etc.), and asserts the first
    (from, to) transition recorded by patching store.advance.
    """

    def _sequenced(self, responses: list) -> MagicMock:
        """Provider whose exec_agent returns responses in order, then DONE."""
        idx = {"n": 0}
        provider = _mock_provider()

        def _side_effect(*args, **kwargs):
            if "COMMANDER JUDGMENT REQUEST" in str(args[1]):
                return SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "JUDGMENT_RESOLVED",
                        "state_updates": {},
                    },
                    raw_output="",
                    duration_ms=0,
                    timed_out=False,
                )
            i = idx["n"]
            idx["n"] += 1
            verdict, updates = responses[i] if i < len(responses) else ("DONE", {})
            return SquadAgentResult(
                exit_code=0,
                echelon_result={"verdict": verdict, "state_updates": updates},
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )

        provider.exec_agent.side_effect = _side_effect
        return provider

    def _run_and_capture(
        self,
        tmp_path: Path,
        start_phase: str,
        initial_state: dict,
        provider: MagicMock,
    ) -> list:
        """Run from start_phase and return list of (from_phase, to_phase) transitions."""
        ctrl, store = _controller(tmp_path, provider)
        store.initialize("r", "banzai", "msg", 0, start_phase)
        state = store.load()
        state.update(initial_state)
        store.save(state)
        _mark_constitution_complete(tmp_path, store)

        with patch.object(store, "advance", wraps=store.advance) as spy:
            ctrl.run("msg", "banzai")

        return [(c.args[0], c.args[1]) for c in spy.call_args_list]

    # Shared terminal tail: once a gate passes, drive to build-done quickly.
    # Sequence after the gate under test: implement→spec-guard→code-review→
    # test-guard→progress(all_done)→build-8-finalize(no-op)→build-done.
    _TAIL_FROM_IMPLEMENT = [
        ("DONE", {}),                # implement → spec-guard
        ("PASS", {}),                # spec-guard → code-review
        ("APPROVED", {}),            # code-review → test-guard
        ("PASS", {}),                # test-guard → progress
        ("DONE", {"all_tasks_complete": True, "no_more_phase_checkpoints": True}),
    ]
    _TAIL_FROM_SPEC_GUARD = [
        ("PASS", {}),                # spec-guard → code-review
        ("APPROVED", {}),            # code-review → test-guard
        ("PASS", {}),                # test-guard → progress
        ("DONE", {"all_tasks_complete": True, "no_more_phase_checkpoints": True}),
    ]
    _TAIL_FROM_CODE_REVIEW = [
        ("APPROVED", {}),            # code-review → test-guard
        ("PASS", {}),                # test-guard → progress
        ("DONE", {"all_tasks_complete": True, "no_more_phase_checkpoints": True}),
    ]
    _TAIL_FROM_TEST_GUARD = [
        ("PASS", {}),                # test-guard → progress
        ("DONE", {"all_tasks_complete": True, "no_more_phase_checkpoints": True}),
    ]
    _TAIL_FROM_PROGRESS = [
        ("DONE", {"all_tasks_complete": True, "no_more_phase_checkpoints": True}),
    ]

    # ── build-3-spec-guard ──────────────────────────────────────────────────

    def test_spec_guard_fail_early_routes_to_implement(self, tmp_path):
        """FAIL AND fix_cycle < 2 → implement (fix cycle)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-3-spec-guard",
            initial_state={"fix_cycle": 0},
            provider=self._sequenced(
                [("FAIL", {})] + self._TAIL_FROM_IMPLEMENT
            ),
        )
        assert transitions[0] == ("build-3-spec-guard", "build-2-implement")

    def test_spec_guard_fail_late_routes_to_code_review(self, tmp_path):
        """FAIL AND fix_cycle >= 2 → code-review (DEGRADED, skip back-route)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-3-spec-guard",
            initial_state={"fix_cycle": 2},
            provider=self._sequenced(
                [("FAIL", {})] + self._TAIL_FROM_CODE_REVIEW
            ),
        )
        assert transitions[0] == ("build-3-spec-guard", "build-4-code-review")

    # ── build-4-code-review ─────────────────────────────────────────────────

    def test_code_review_changes_early_routes_to_implement(self, tmp_path):
        """CHANGES_REQUESTED AND fix_cycle < 2 → implement."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-4-code-review",
            initial_state={"fix_cycle": 0},
            provider=self._sequenced(
                [("CHANGES_REQUESTED", {})] + self._TAIL_FROM_IMPLEMENT
            ),
        )
        assert transitions[0] == ("build-4-code-review", "build-2-implement")

    def test_code_review_changes_late_routes_to_test_guard(self, tmp_path):
        """CHANGES_REQUESTED AND fix_cycle >= 2 → test-guard (DEGRADED)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-4-code-review",
            initial_state={"fix_cycle": 2},
            provider=self._sequenced(
                [("CHANGES_REQUESTED", {})] + self._TAIL_FROM_TEST_GUARD
            ),
        )
        assert transitions[0] == ("build-4-code-review", "build-5-test-guard")

    # ── build-5-test-guard ──────────────────────────────────────────────────

    def test_test_guard_fail_early_routes_to_implement(self, tmp_path):
        """FAIL AND fix_cycle < 2 → implement."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-5-test-guard",
            initial_state={"fix_cycle": 0},
            provider=self._sequenced(
                [("FAIL", {})] + self._TAIL_FROM_IMPLEMENT
            ),
        )
        assert transitions[0] == ("build-5-test-guard", "build-2-implement")

    def test_test_guard_fail_late_routes_to_progress(self, tmp_path):
        """FAIL AND fix_cycle >= 2 → progress (DEGRADED)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-5-test-guard",
            initial_state={"fix_cycle": 2},
            provider=self._sequenced(
                [("FAIL", {})] + self._TAIL_FROM_PROGRESS
            ),
        )
        assert transitions[0] == ("build-5-test-guard", "build-6-progress")

    # ── build-6-progress ────────────────────────────────────────────────────

    def test_progress_all_done_routes_to_documentation(self, tmp_path):
        """all_tasks_complete AND no_more_phase_checkpoints → build-8-documentation."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-6-progress",
            initial_state={},
            provider=self._sequenced(
                [("DONE", {"all_tasks_complete": True, "no_more_phase_checkpoints": True})]
            ),
        )
        assert transitions[0] == ("build-6-progress", "build-8-documentation")

    def test_progress_more_tasks_routes_to_implement(self, tmp_path):
        """more_tasks_in_phase_group → build-2-implement (next task)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-6-progress",
            initial_state={"more_tasks_in_phase_group": True},
            provider=self._sequenced(
                [("DONE", {})] + self._TAIL_FROM_IMPLEMENT
            ),
        )
        assert transitions[0] == ("build-6-progress", "build-2-implement")

    # ── build-7-integration ─────────────────────────────────────────────────

    def test_integration_fail_early_routes_to_implement(self, tmp_path):
        """FAIL AND fix_cycle < 2 → implement."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-7-integration",
            initial_state={"fix_cycle": 0},
            provider=self._sequenced(
                [("FAIL", {})] + self._TAIL_FROM_IMPLEMENT
            ),
        )
        assert transitions[0] == ("build-7-integration", "build-2-implement")

    def test_integration_fail_late_routes_to_documentation(self, tmp_path):
        """FAIL AND fix_cycle >= 2 → build-8-documentation (DEGRADED)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-7-integration",
            initial_state={"fix_cycle": 2},
            provider=self._sequenced([("FAIL", {})]),
        )
        assert transitions[0] == ("build-7-integration", "build-8-documentation")

    def test_integration_pass_more_groups_routes_to_implement(self, tmp_path):
        """PASS AND more_phase_groups → implement (next phase group)."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-7-integration",
            initial_state={"more_phase_groups": True},
            provider=self._sequenced(
                [("PASS", {})] + self._TAIL_FROM_IMPLEMENT
            ),
        )
        assert transitions[0] == ("build-7-integration", "build-2-implement")

    def test_integration_pass_all_done_routes_to_documentation(self, tmp_path):
        """PASS AND all_phase_groups_complete → build-8-documentation."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-7-integration",
            initial_state={"all_phase_groups_complete": True},
            provider=self._sequenced([("PASS", {})]),
        )
        assert transitions[0] == ("build-7-integration", "build-8-documentation")

    def test_documentation_routes_to_docs_verifier(self, tmp_path):
        """TECH WRITER output is verified before build finalization."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-8-documentation",
            initial_state={},
            provider=self._sequenced([("DONE", {})]),
        )
        assert transitions[0] == ("build-8-documentation", "build-8-verify-docs")

    def test_docs_verifier_pass_routes_to_finalize(self, tmp_path):
        """Docs verifier PASS → build-8-finalize."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-8-verify-docs",
            initial_state={},
            provider=self._sequenced([("PASS", {})]),
        )
        assert transitions[0] == ("build-8-verify-docs", "build-8-finalize")

    def test_docs_verifier_fail_routes_to_documentation_repair(self, tmp_path):
        """Docs verifier FAIL → TECH WRITER repair loop."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-8-verify-docs",
            initial_state={},
            provider=self._sequenced([("FAIL", {})]),
        )
        assert transitions[0] == ("build-8-verify-docs", "build-8-documentation")

    # ── build-2-implement (self-loop on NEEDS_CONTEXT) ──────────────────────

    def test_implement_needs_context_early_retries(self, tmp_path):
        """NEEDS_CONTEXT AND retry_count < 2 → self-loop back to implement."""
        transitions = self._run_and_capture(
            tmp_path,
            start_phase="build-2-implement",
            initial_state={"retry_count": 0},
            provider=self._sequenced(
                [("NEEDS_CONTEXT", {})] + self._TAIL_FROM_IMPLEMENT
            ),
        )
        assert transitions[0] == ("build-2-implement", "build-2-implement")


def test_journal_written_to_squad_dir_not_specify(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    (squad_dir / "staging").mkdir()
    ctrl, store = _controller(tmp_path, squad_dir=squad_dir)
    store.initialize("r", "banzai", "msg", 0, "init")
    from harness.squad_provider import SquadAgentResult
    ctrl._provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": "DONE", "state_updates": {},
                        "journal_entries": [{"type": "insight"}]},
        raw_output="", duration_ms=0, timed_out=False,
    )
    ctrl.run("msg", "banzai")
    assert (squad_dir / "reasoning-journal.jsonl").exists()
    assert not (tmp_path / ".specify/squad/reasoning-journal.jsonl").exists()


class TestConstitutionPhase:
    """Regression: phase1-constitution must dispatch CHIEF (agent), not be a no-op."""

    def test_phase1_constitution_is_agent_not_commander_internal(self, tmp_path):
        """phase1-constitution must be type=agent so CHIEF gets dispatched."""
        graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
        node = graph.get("phase1-constitution")
        assert node.type == "agent", (
            f"phase1-constitution must be type=agent (so CHIEF is dispatched by the harness). "
            f"Got: {node.type!r}. commander_internal silently skips the phase."
        )

    def test_phase1_constitution_agent_is_chief_not_commander(self, tmp_path):
        """phase1-constitution must dispatch CHIEF, not COMMANDER."""
        graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
        node = graph.get("phase1-constitution")
        assert node.agent == "echelon.chief", (
            f"phase1-constitution must dispatch echelon.chief. "
            f"Got: {node.agent!r}. COMMANDER must not own constitution creation."
        )

    def test_chief_resolves_to_agent_file(self, tmp_path):
        """echelon-chief must resolve to a real agent file path."""
        graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
        rel = graph.agent_file("echelon.chief")
        assert rel == str((PROSAIC_SUBAGENTS / "echelon.chief.md").resolve()), (
            f"echelon.chief should resolve to its Prosaic source. Got: {rel!r}."
        )
        agent_path = Path(rel)
        assert agent_path.exists(), f"Agent file not found: {agent_path}"

    def test_chief_has_constitution_context_pack(self, tmp_path):
        """phase1-constitution must include staging artifacts in context_pack."""
        graph = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS)
        node = graph.get("phase1-constitution")
        pack = " ".join(node.context_pack)
        assert "user-intent.md" in pack
        assert "glossary" in pack
        assert "mental-model" in pack
        assert "boundaries" in pack
        assert "assumptions" in pack
        assert "user-intent" in pack

    def test_phase1_what_requires_constitution_completion_provenance(self, tmp_path):
        """Existing-spec resumes must not skip CHIEF/phase1-constitution."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")

        guarded = ctrl._guard_constitution_provenance("phase1-what")

        assert guarded == "phase1-constitution"
        assert store.load()["phase"] == "phase1-constitution"

    def test_pre_constitution_context_phases_do_not_require_constitution_provenance(self):
        """TRACKER must run before CHIEF so user-intent.md exists for constitution."""
        for phase in [
            "init",
            "phase1-discover",
            "phase1-synthesizer",
            "phase1-modeler",
            "phase1-tracker",
            "phase1-why1",
            "phase1-constitution",
        ]:
            assert _phase_requires_constitution_provenance(phase) is False

    def test_phase1_what_still_requires_constitution_provenance(self):
        assert _phase_requires_constitution_provenance("phase1-what") is True

    def test_run_dispatches_chief_before_phase1_what_without_provenance(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        (ctrl._squad_dir / "constitution.draft.md").write_text(
            "# Project Constitution\n\n## Core Principles\n\nReal rules.\n",
            encoding="utf-8",
        )

        with patch.object(ctrl, "_evaluate_transitions", return_value="DONE"):
            result = ctrl.run("msg", "banzai")

        assert result.status == "done"
        assert store.load()["last_dispatch"]["phase_id"] == "phase1-constitution"
        first_prompt = provider.exec_agent.call_args.args[1]
        assert "echelon.chief" in first_prompt

    def test_phase1_what_allowed_after_constitution_completion_provenance(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        state = store.load()
        state["completed_phases"] = ["phase1-constitution"]
        store.save(state)
        const_path = tmp_path / ".echelon" / "constitution.md"
        const_path.parent.mkdir(parents=True, exist_ok=True)
        const_path.write_text("# Constitution\n\nReal rules.\n", encoding="utf-8")

        assert ctrl._guard_constitution_provenance("phase1-what") == "phase1-what"

    def test_constitution_guard_allows_sync_impact_report_placeholder_history(self, tmp_path):
        const_path = tmp_path / ".echelon" / "constitution.md"
        const_path.parent.mkdir(parents=True, exist_ok=True)
        const_path.write_text(
            """<!--
Sync Impact Report
Modified principles:
  - [PRINCIPLE_1_NAME] -> I. Real Principle
-->

# Constitution

## Core Principles

### I. Real Principle

Ready.
""",
            encoding="utf-8",
        )

        assert _constitution_artifact_is_real(tmp_path) is True

    def test_constitution_guard_rejects_body_placeholder_after_sync_report(self, tmp_path):
        const_path = tmp_path / ".echelon" / "constitution.md"
        const_path.parent.mkdir(parents=True, exist_ok=True)
        const_path.write_text(
            """<!--
Sync Impact Report
Modified principles:
  - [PRINCIPLE_1_NAME] -> I. Real Principle
-->

# Constitution

## Core Principles

### [PRINCIPLE_2_NAME]
""",
            encoding="utf-8",
        )

        assert _constitution_artifact_is_real(tmp_path) is False

    def test_greenfield_modeler_phase_is_skipped_before_dispatch(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        checkpoint_dispatches: list[dict] = []

        def observe_checkpoint(*_args):
            checkpoint_dispatches.append(
                deepcopy(store.load()["last_dispatch"])
            )
            return True

        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            observe_checkpoint,
        )

        result = ctrl.run_single_phase("phase1-modeler", "msg", "banzai")
        state = store.load()

        assert result.status == "running"
        assert state["phase"] == "phase1-tracker"
        assert state["last_dispatch"]["phase_id"] == "phase1-modeler"
        assert state["last_dispatch"]["conditional_skip"] is True
        assert state["last_dispatch"]["manual_phase_run"] is True
        assert state["last_dispatch"]["post_dispatch_complete"] is True
        assert "phase1-modeler" in state["completed_phases"]
        assert checkpoint_dispatches == []
        assert PENDING_CONTROLLER_COMPLETION_KEY not in state
        provider.exec_agent.assert_not_called()

    def test_completed_constitution_with_missing_artifact_blocks(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase1-what")
        state = store.load()
        state["completed_phases"] = ["phase1-constitution"]
        store.save(state)

        assert ctrl._guard_constitution_provenance("phase1-what") == "terminal-blocked"
        state = store.load()
        assert state["status"] == "blocked"
        assert state["blocked_reason"] == "constitution_artifact_mismatch"

    def test_chief_dispatched_in_controller(self, tmp_path):
        """SquadController dispatches an agent (not no-op) for phase1-constitution."""
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-constitution")
        ctrl.run("msg", "banzai")
        # AgentExecutor calls exec_agent; CommanderInternalExecutor does not.
        assert provider.exec_agent.called, (
            "exec_agent was not called — phase1-constitution is still a harness no-op. "
            "It must be type=agent so CHIEF gets dispatched."
        )

    def test_controller_promotes_chief_run_local_draft_before_advancing(
        self,
        tmp_path: Path,
    ) -> None:
        """CHIEF never needs write authority over the protected .echelon root."""
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-constitution")
        draft = ctrl._squad_dir / "constitution.draft.md"
        draft.write_text(
            "# Project Constitution\n\n## Core Principles\n\nReal rules.\n",
            encoding="utf-8",
        )

        with patch.object(ctrl, "_evaluate_transitions", return_value="DONE"):
            result = ctrl.run("msg", "banzai")

        canonical = tmp_path / ".echelon" / "constitution.md"
        assert result.status == "done"
        assert canonical.read_text(encoding="utf-8") == draft.read_text(
            encoding="utf-8"
        )
        assert store.load()["constitution_status"] == "exists"
        assert "phase1-constitution" in store.load()["completed_phases"]

    def test_controller_refuses_incomplete_chief_draft_without_advancing(
        self,
        tmp_path: Path,
    ) -> None:
        """An incomplete draft cannot create constitution provenance."""
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider)
        store.initialize("r", "banzai", "msg", 0, "phase1-constitution")
        (ctrl._squad_dir / "constitution.draft.md").write_text(
            "# [PROJECT_NAME] Constitution\n",
            encoding="utf-8",
        )

        result = ctrl.run("msg", "banzai")

        state = store.load()
        assert result.status == "blocked"
        assert state["phase"] == "terminal-blocked"
        assert state["blocked_reason"] == "constitution_draft_invalid"
        assert "phase1-constitution" not in state["completed_phases"]
        assert not (tmp_path / ".echelon" / "constitution.md").exists()

    def test_controller_stages_canonical_snapshot_for_chief_amendment(
        self,
        tmp_path: Path,
    ) -> None:
        """Amendment mode reads only the controller-managed run-local copy."""
        ctrl, _store = _controller(tmp_path)
        canonical = tmp_path / ".echelon" / "constitution.md"
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text(
            "# Project Constitution\n\n## Core Principles\n\nReal rules.\n",
            encoding="utf-8",
        )

        ctrl._materialize_controller_phase_inputs(
            ctrl._graph.get("phase1-constitution")
        )

        assert (ctrl._squad_dir / "constitution.current.md").read_text(
            encoding="utf-8"
        ) == canonical.read_text(encoding="utf-8")


class TestCommanderJudgmentStateUpdates:
    @staticmethod
    def _ambiguous_node() -> PhaseNode:
        return PhaseNode(
            id="phase1-discover",
            type="agent",
            transitions=[
                {
                    "to": "phase1-why1",
                    "condition": "quality_gates.pass",
                }
            ],
        )

    @staticmethod
    def _phase_result() -> SquadAgentResult:
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

    def test_unknown_judgment_reporting_state_is_quarantined_before_mutation(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "JUDGMENT_RESOLVED",
                "state_updates": {
                    "next_phase": "phase1-why1",
                    "unauthorized_key": "must-not-persist",
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-discover",
        )

        next_phase = _coordinate_prepared_result(ctrl,
            self._ambiguous_node(),
            self._phase_result(),
        )
        state = store.load()

        assert next_phase == "phase1-why1"
        assert state.get("status") != "blocked"
        assert "unauthorized_key" not in state
        journal = tmp_path / "squad" / "run-test" / "reasoning-journal.jsonl"
        entries = [json.loads(line) for line in journal.read_text().splitlines()]
        assert entries[0]["type"] == "state_contract_warning"
        assert entries[0]["data"]["dropped_keys"] == ["unauthorized_key"]

    def test_judgment_cannot_own_store_iteration(self, tmp_path):
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "JUDGMENT_RESOLVED",
                "state_updates": {
                    "next_phase": "phase1-why1",
                    "iteration": 2,
                },
                "journal_entries": [
                    {
                        "type": "decision",
                        "agent": "echelon-commander",
                        "data": {"decision": "must-not-persist"},
                    }
                ],
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        node = self._ambiguous_node()
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            node.id,
        )
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(
            node,
            self._phase_result(),
            snapshot,
        )
        before = store.load()

        with pytest.raises(ControllerStateContractViolation) as raised:
            ctrl._coordinate_transition_routing(
                node,
                prepared,
                snapshot,
            )

        assert raised.value.validator == "ownership"
        assert raised.value.json_path == "$.state_updates.iteration"
        assert store.load() == before
        assert not (
            tmp_path / "squad" / "run-test" / "reasoning-journal.jsonl"
        ).exists()

    @pytest.mark.parametrize(
        ("exit_code", "timed_out", "provider_limit_message"),
        [
            (7, False, ""),
            (0, True, ""),
            (0, False, "provider quota exhausted"),
        ],
    )
    def test_ordinary_judgment_operational_failure_hits_typed_boundary(
        self,
        tmp_path: Path,
        exit_code: int,
        timed_out: bool,
        provider_limit_message: str,
    ) -> None:
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=exit_code,
            echelon_result={
                "verdict": "JUDGMENT_RESOLVED",
                "state_updates": {"next_phase": "phase1-why1"},
            },
            raw_output="",
            duration_ms=0,
            timed_out=timed_out,
            provider_limit_message=provider_limit_message,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        node = self._ambiguous_node()
        store.initialize("r", "greenfield", "msg", 0, node.id)
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(
            node,
            self._phase_result(),
            snapshot,
        )

        decision = ctrl._construct_routing_decision_or_block(
            node,
            prepared,
            snapshot,
        )

        assert decision is None
        blocked = store.load()
        assert blocked["phase"] == node.id
        assert blocked["last_dispatch"] is None
        assert blocked["controller_contract_error"]["contract"] == "judgment"
        assert (
            blocked["controller_contract_error"]["validator"]
            == "operational_success"
        )

    def test_ordinary_blocked_judgment_cannot_select_next_phase(
        self,
        tmp_path: Path,
    ) -> None:
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "BLOCKED",
                "state_updates": {
                    "next_phase": "phase1-why1",
                    "status": "blocked",
                    "blocked_reason": "needs clarification",
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        node = self._ambiguous_node()
        store.initialize("r", "greenfield", "msg", 0, node.id)
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(
            node,
            self._phase_result(),
            snapshot,
        )

        decision = ctrl._construct_routing_decision_or_block(
            node,
            prepared,
            snapshot,
        )

        assert decision is None
        blocked = store.load()
        assert blocked["phase"] == node.id
        assert blocked["last_dispatch"] is None
        assert (
            blocked["controller_contract_error"]["validator"]
            == "blocked_intent"
        )

    def test_ordinary_blocked_judgment_commits_exact_self_loop_intent(
        self,
        tmp_path: Path,
    ) -> None:
        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "BLOCKED",
                "state_updates": {
                    "status": "blocked",
                    "blocked_reason": "needs clarification",
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        node = self._ambiguous_node()
        store.initialize("r", "greenfield", "msg", 0, node.id)

        next_phase = _coordinate_prepared_result(
            ctrl,
            node,
            self._phase_result(),
        )

        blocked = store.load()
        assert next_phase == node.id
        assert blocked["phase"] == node.id
        assert blocked["status"] == "blocked"
        assert blocked["blocked_reason"] == "needs clarification"
        assert "escalation_question" not in blocked

    def test_terminal_blocked_never_runs_phase_a_finalization(self, tmp_path):
        """A terminal block is a stop state, even if an earlier handler set running."""
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "terminal-blocked", max_iterations=5)
        state = store.load()
        state.update(
            {
                "status": "running",
                "blocked_reason": "consecutive_why_fails",
                "escalation_question": "Two consecutive WHY2 failures",
            }
        )
        store.save(state)

        with patch.object(ctrl, "_publish_terminal_phase_a_artifacts_if_available") as publish:
            result = ctrl.run("msg", "banzai")

        assert result.status == "blocked"
        assert store.load()["blocked_reason"] == "consecutive_why_fails"
        publish.assert_not_called()

    def test_governance_block_merged_into_eval_state(self, tmp_path):
        ctrl, _ = _controller(tmp_path)
        cfg = ctrl._governance_config()
        assert cfg.get("governance", {}).get("enabled") is True
        assert cfg["feasibility_structural_pass"] is False
        assert cfg["intent_alignment_check_structural_pass"] is False

    def test_gate_config_uses_local_overrides_and_extension_defaults(self, tmp_path):
        config_dir = tmp_path / ".echelon"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text(
            "lexicon_gate:\n"
            "  enabled: true\n",
            encoding="utf-8",
        )
        (config_dir / "local.yml").write_text(
            "lexicon_gate:\n"
            "  artifacts:\n"
            "    tasks:\n"
            "      enabled: false\n",
            encoding="utf-8",
        )

        ctrl, _ = _controller(tmp_path)
        gate = ctrl._lexicon_gate_config()["lexicon_gate"]

        assert gate["enabled"] is True
        assert gate["artifacts"]["spec"]["enabled"] is True
        assert gate["artifacts"]["tasks"]["enabled"] is False

    def test_disabled_tasks_subgate_is_routing_inert(self, tmp_path):
        config_dir = tmp_path / ".echelon"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text(
            "lexicon_gate:\n"
            "  enabled: true\n"
            "  artifacts:\n"
            "    tasks:\n"
            "      enabled: false\n",
            encoding="utf-8",
        )
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase3-plan")
        store.initialize("r", "banzai", "msg", 0, "phase3-plan", max_iterations=3)

        result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        with patch.object(
            ctrl,
            "_judgment_dispatch",
            side_effect=AssertionError("disabled tasks gate dispatched COMMANDER"),
        ):
            assert _evaluate_prepared_result(ctrl, node, result) == "phase3-tasks-lexicon"
            gate = ctrl._graph.get("phase3-tasks-lexicon")
            gate_result = ctrl._executors["deterministic_lexicon"].execute(gate, store)
            assert gate_result.state_updates["tasks_lexicon_action"] == "proceed"
            assert _evaluate_prepared_result(ctrl, gate, gate_result) == "phase3-understanding"


class TestStructuralGuardDeterminism:
    """Regression: phase2-decide with feasibility_structural_pass=False must
    re-dispatch deterministically via ConditionEvaluator — never punt to COMMANDER.

    The condition is:
      governance.enabled AND NOT feasibility_structural_pass AND iteration < max_iterations
    All three operands are resolvable state keys once the governance config is
    merged into eval_state (via _governance_config). The test patches
    _judgment_dispatch to RAISE, proving no COMMANDER punt occurs.
    """

    @staticmethod
    def _result(updates):
        from harness.squad_provider import SquadAgentResult
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "PASS", "state_updates": updates},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

    def test_feasibility_fail_redispatches_without_commander(self, tmp_path):
        from unittest.mock import patch
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-decide")
        st = store.load()
        st["iteration"] = 0
        st["max_iterations"] = 3
        st["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(st)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("guard punted to COMMANDER")):
            nxt = _evaluate_prepared_result(
                ctrl,
                node,
                self._result({}),
            )
        assert nxt == "phase2-feasibility-structural"

    def test_omitted_feasibility_structural_result_does_not_fail_open(self, tmp_path):
        from unittest.mock import patch
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-decide")
        st = store.load()
        st["iteration"] = 0
        st["max_iterations"] = 3
        store.save(st)
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "PASS", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("guard punted to COMMANDER")):
            nxt = _evaluate_prepared_result(ctrl, node, result)

        assert nxt == "phase2-feasibility-structural"

    def test_omitted_intent_alignment_structural_result_does_not_fail_open(self, tmp_path):
        from unittest.mock import patch
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-tracker-alignment")
        st = store.load()
        st["iteration"] = 0
        st["max_iterations"] = 3
        store.save(st)
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "ALIGNED", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("guard punted to COMMANDER")):
            nxt = _evaluate_prepared_result(ctrl, node, result)

        assert nxt == "phase2-intent-alignment-structural"

    def test_invalid_feasibility_artifact_overrides_stale_model_pass(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-decide")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "feasibility.md").write_text("# Incomplete\n", encoding="utf-8")
        state = store.load()
        state.update({
            "phase": node.id,
            "iteration": 0,
            "max_iterations": 5,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
        })
        store.save(state)

        result = self._result({})
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(node, result, snapshot)
        assert (
            ctrl._evaluate_transitions(node, prepared, snapshot)
            == "phase2-feasibility-structural"
        )
        assert result.state_updates == {}
        assert prepared.state_updates["feasibility_verdict"] == "PASS"
        state = store.load()
        state.update(
            {
                "phase": "phase2-feasibility-structural",
                "feasibility_verdict": "PASS",
            }
        )
        store.save(state)
        gate_node = ctrl._graph.get("phase2-feasibility-structural")
        gate_result = ctrl._executors["deterministic_structural"].execute(
            gate_node, store
        )
        assert gate_result.state_updates["feasibility_structural_pass"] is False
        report = json.loads(
            Path(gate_result.state_updates["feasibility_structural_report"]).read_text(
                encoding="utf-8"
            )
        )
        assert report["ok"] is False
        assert report["findings"]

    def test_valid_feasibility_artifact_overrides_stale_model_failure(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-decide")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "feasibility.md").write_text(
            "# Feasibility\n\n"
            "## Metadata\nSpec: demo\n\n"
            "## Feasibility Verdict\nTechnical, resource, and domain feasibility confirmed.\n\n"
            "## Key Risks\nNo blocking risks.\n\n"
            "## Kill / Defer / Pass Decision\nDecision: PASS\n",
            encoding="utf-8",
        )
        state = store.load()
        state.update({
            "phase": node.id,
            "iteration": 0,
            "max_iterations": 5,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
        })
        store.save(state)

        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "PASS",
                "state_updates": {},
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(node, result, snapshot)
        assert (
            ctrl._evaluate_transitions(node, prepared, snapshot)
            == "phase2-feasibility-structural"
        )
        assert result.state_updates == {}
        assert prepared.state_updates["feasibility_verdict"] == "PASS"

    def test_governance_warn_exhaustion_is_explicit(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-feasibility-structural")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "feasibility.md").write_text("# Incomplete\n", encoding="utf-8")
        state = store.load()
        state.update({
            "phase": node.id,
            "iteration": 3,
            "max_iterations": 5,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "feasibility_structural_attempts": 3,
            "feasibility_verdict": "PASS",
        })
        store.save(state)

        result = ctrl._executors["deterministic_structural"].execute(node, store)
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(node, result, snapshot)
        assert (
            ctrl._evaluate_transitions(node, prepared, snapshot)
            == "phase2-strategic-overview"
        )
        assert result.verdict == "WARN"
        assert prepared.state_updates["governance_gate_exhausted"] == "feasibility"

    def test_governance_block_exhaustion_stops_pipeline(self, tmp_path):
        config_dir = tmp_path / ".echelon"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text(
            "governance:\n"
            "  enabled: true\n"
            "  max_repair_attempts: 1\n"
            "  on_exhausted: block\n",
            encoding="utf-8",
        )
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-feasibility-structural")
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            node.id,
        )
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "feasibility.md").write_text("# Incomplete\n", encoding="utf-8")
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 5,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "feasibility_verdict": "PASS",
        })
        store.save(state)

        result = ctrl._executors["deterministic_structural"].execute(node, store)
        assert _coordinate_prepared_result(ctrl, node, result) == "terminal-blocked"
        assert store.load()["blocked_reason"] == "governance_structural_exhausted"

    def test_governance_enrichment_does_not_mutate_provider_result(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-decide")
        provider_result = self._result({"status": "blocked"})
        original = deepcopy(provider_result.echelon_result)

        enrichment = ctrl._controller_enrichment(
            node,
            store.load(),
            provider_result,
        )

        assert provider_result.echelon_result == original
        assert enrichment.updates["feasibility_verdict"] == "PASS"
        assert enrichment.controller_owns_result_updates is False

    def test_governance_hard_exhaustion_is_an_unpersisted_routing_override(
        self,
        tmp_path: Path,
    ) -> None:
        config_dir = tmp_path / ".echelon"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text(
            "governance:\n"
            "  enabled: true\n"
            "  max_repair_attempts: 1\n"
            "  on_exhausted: block\n",
            encoding="utf-8",
        )
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase2-decide")
        before_state = store.load()
        provider_result = self._result({})
        original = deepcopy(provider_result.echelon_result)

        enrichment = ctrl._controller_enrichment(
            node,
            before_state,
            provider_result,
        )

        assert enrichment.routing_override is None
        assert enrichment.updates["feasibility_verdict"] == "PASS"
        assert store.load() == before_state
        assert provider_result.echelon_result == original


class TestPreparedTransitionBoundary:
    def test_transition_evaluation_does_not_mutate_prepared_result_or_state(
        self,
        tmp_path: Path,
    ) -> None:
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "banzai",
            "msg",
            0,
            "phase3-tasks-lexicon",
            max_iterations=5,
        )
        node = ctrl._graph.get("phase3-tasks-lexicon")
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": {
                    "tasks_lexicon_action": "proceed",
                    "tasks_lexicon_pass": True,
                    "tasks_lexicon_attempts": 0,
                    "tasks_lexicon_findings": 0,
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(node, result, snapshot)
        before_state = store.load()
        before_payload = prepared.echelon_result

        assert (
            ctrl._evaluate_transitions(node, prepared, snapshot)
            == "phase3-understanding"
        )
        assert store.load() == before_state
        assert prepared.echelon_result == before_payload

    def test_state_mutation_after_evaluation_before_sealing_rejects_stale_route(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        TestFailClosedControllerPreparation._patch_run_guards(
            ctrl,
            monkeypatch,
        )
        executor = MagicMock()
        executor.execute.return_value = (
            TestFailClosedControllerPreparation._tasks_result(True)
        )
        ctrl._executors["deterministic_lexicon"] = executor
        success_effects: list[str] = []
        original_evaluate = ctrl._evaluate_transitions

        def evaluate_then_publish_concurrent_state(
            node: PhaseNode,
            prepared,
            snapshot,
        ):
            to_phase = original_evaluate(node, prepared, snapshot)
            concurrent = store.load()
            concurrent["concurrent_marker"] = "published"
            store.save(concurrent)
            return to_phase

        monkeypatch.setattr(
            ctrl,
            "_evaluate_transitions",
            evaluate_then_publish_concurrent_state,
        )
        monkeypatch.setattr(
            ctrl,
            "_apply_product_input_updates",
            lambda *_: success_effects.append("product"),
        )
        monkeypatch.setattr(
            store,
            "advance",
            lambda *_args, **_kwargs: success_effects.append("advance"),
        )
        monkeypatch.setattr(
            ctrl,
            "_apply_declared_phase_timing_transition",
            lambda *_: success_effects.append("timing"),
        )
        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            lambda *_: success_effects.append("checkpoint"),
        )

        result = ctrl.run_single_phase(
            "phase3-tasks-lexicon",
            "validate",
            "banzai",
        )
        state = store.load()

        assert result.phase == "phase3-tasks-lexicon"
        assert result.status == "running"
        assert state["concurrent_marker"] == "published"
        assert "controller_contract_error" not in state
        assert state["last_dispatch"] is None
        assert success_effects == []


class TestFailClosedControllerPreparation:
    @staticmethod
    def _tasks_result(
        pass_value: object,
        *,
        action: str = "proceed",
    ) -> SquadAgentResult:
        return SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": {
                    "tasks_lexicon_action": action,
                    "tasks_lexicon_pass": pass_value,
                    "tasks_lexicon_attempts": 0,
                    "tasks_lexicon_findings": 0,
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

    @staticmethod
    def _consensus_result() -> SquadAgentResult:
        return SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "PASS",
                "state_updates": {
                    "gate_decision": "PASS",
                    "phase_recommendation": "proceed-to-build",
                    "implementability_metrics": {"ready_ratio": 1.0},
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

    @staticmethod
    def _patch_run_guards(
        ctrl: SquadController,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            ctrl,
            "_guard_spec_lexicon_evidence",
            lambda phase: phase,
        )
        monkeypatch.setattr(
            ctrl,
            "_guard_understanding_evidence",
            lambda phase: phase,
        )
        monkeypatch.setattr(
            ctrl,
            "_guard_constitution_provenance",
            lambda phase: phase,
        )
        monkeypatch.setattr(ctrl, "_refresh_run_context", lambda *_: None)
        monkeypatch.setattr(ctrl, "_ensure_telemetry_manifest", lambda: None)
        monkeypatch.setattr(ctrl, "_attach_published_re_context", lambda: None)

    @staticmethod
    def _patch_success_steps(
        ctrl: SquadController,
        store: SquadStateStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> list[str]:
        calls: list[str] = []
        monkeypatch.setattr(
            ctrl,
            "_prepare_external_phase_effects",
            lambda *_args, **_kwargs: calls.append("stage"),
        )
        monkeypatch.setattr(
            ctrl,
            "_coordinate_transition_routing",
            lambda *_: calls.append("routing"),
        )
        monkeypatch.setattr(
            ctrl,
            "_apply_declared_phase_timing_transition",
            lambda *_: calls.append("timing"),
        )
        monkeypatch.setattr(
            store,
            "advance",
            lambda *_args, **_kwargs: calls.append("advance"),
        )
        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            lambda *_: calls.append("checkpoint"),
        )
        return calls

    def test_phase3_consensus_fields_are_controller_owned(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase3-consensus",
        )
        node = ctrl._graph.get("phase3-consensus")
        snapshot = store.capture_routing_snapshot(
            expected_phase="phase3-consensus"
        )

        prepared = ctrl._prepare_phase_result_or_block(
            node,
            self._consensus_result(),
            snapshot,
        )

        assert prepared is not None
        assert prepared.controller_update_keys == {
            "gate_decision",
            "phase_recommendation",
            "implementability_metrics",
        }
        assert prepared.provider_update_keys == set()
        assert prepared.controller_contract_name == "consensus_gate"

    def test_phase3_consensus_warned_tasks_gate_does_not_leak_spec_waiver(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / ".echelon").mkdir()
        (tmp_path / ".echelon" / "config.yml").write_text(
            "lexicon_gate:\n"
            "  enabled: true\n"
            "  max_repair_attempts: 3\n"
            "  on_exhausted: warn\n"
            "  artifacts:\n"
            "    tasks:\n"
            "      enabled: true\n",
            encoding="utf-8",
        )
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase3-consensus",
        )
        state = store.load()
        state.update(
            {
                "tasks_lexicon_pass": False,
                "tasks_lexicon_attempts": 3,
                "tasks_lexicon_action": "proceed_with_warning",
            }
        )
        store.save(state)
        node = ctrl._graph.get("phase3-consensus")
        snapshot = store.capture_routing_snapshot(
            expected_phase="phase3-consensus"
        )

        prepared = ctrl._prepare_phase_result_or_block(
            node,
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "PASS",
                    "state_updates": {},
                    "journal_entries": [],
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            ),
            snapshot,
        )

        assert prepared is not None
        assert "lexicon_warning_waiver" not in prepared.state_updates
        assert "lexicon_warning_waiver" not in prepared.controller_update_keys

    def test_malformed_controller_output_records_stable_redacted_diagnostic(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase3-tasks-lexicon",
        )
        state = store.load()
        state["completed_phases"] = ["phase1-what"]
        store.save(state)
        node = ctrl._graph.get("phase3-tasks-lexicon")

        first_snapshot = store.capture_routing_snapshot(
            expected_phase=node.id
        )
        assert (
            ctrl._prepare_phase_result_or_block(
                node,
                self._tasks_result("rejected-value-one"),
                first_snapshot,
            )
            is None
        )
        first = store.load()
        first_diagnostic = first["controller_contract_error"]

        second_snapshot = store.capture_routing_snapshot(
            expected_phase=node.id
        )
        assert (
            ctrl._prepare_phase_result_or_block(
                node,
                self._tasks_result("rejected-value-two"),
                second_snapshot,
            )
            is None
        )
        second = store.load()

        assert second["phase"] == node.id
        assert second["status"] == "blocked"
        assert (
            second["blocked_reason"]
            == "controller_state_contract_validation_failed"
        )
        assert second["completed_phases"] == ["phase1-what"]
        assert second["controller_contract_error"] == first_diagnostic
        assert first_diagnostic == {
            "phase_id": node.id,
            "contract": "tasks_lexicon",
            "contract_sha256": node.controller_state_contract.sha256,
            "json_path": "$.state_updates.tasks_lexicon_pass",
            "validator": "const",
            "message": (
                "controller result preparation failed at "
                "$.state_updates.tasks_lexicon_pass (const)"
            ),
        }
        serialized = json.dumps(first_diagnostic, sort_keys=True)
        assert "rejected-value-one" not in serialized
        assert "rejected-value-two" not in serialized

    @pytest.mark.parametrize(
        "probe_factory",
        [_ExplodingPath, _ExplodingMapping, _ExplodingRepr],
        ids=["pathlike", "mapping-iteration", "repr"],
    )
    def test_attestation_protocol_failure_blocks_before_success_effects(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        probe_factory,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        self._patch_run_guards(ctrl, monkeypatch)
        executor = MagicMock()
        malicious = self._tasks_result(True)
        assert malicious.echelon_result is not None
        malicious.echelon_result["attestation_probe"] = probe_factory()
        executor.execute.return_value = malicious
        ctrl._executors["deterministic_lexicon"] = executor
        calls = self._patch_success_steps(ctrl, store, monkeypatch)
        violations: list[ControllerStateContractViolation] = []
        original_prepare = ctrl._prepare_phase_result

        def capture_violation(*args):
            try:
                return original_prepare(*args)
            except ControllerStateContractViolation as exc:
                violations.append(exc)
                raise

        monkeypatch.setattr(
            ctrl,
            "_prepare_phase_result",
            capture_violation,
        )

        result = ctrl.run_single_phase(
            "phase3-tasks-lexicon",
            "validate",
            "banzai",
        )

        assert result.status == "blocked"
        assert result.phase == "phase3-tasks-lexicon"
        assert calls == []
        blocked = store.load()
        assert blocked["completed_phases"] == []
        assert blocked["last_dispatch"] is None
        assert len(violations) == 1
        violation = violations[0]
        assert str(violation) == "untrusted result detachment failed"
        assert violation.contract == "preparation"
        assert violation.json_path == "$.echelon_result.attestation_probe"
        assert violation.validator == "detachment"
        assert violation.__cause__ is None
        assert violation.__context__ is None
        assert blocked["controller_contract_error"] == {
            "phase_id": "phase3-tasks-lexicon",
            "contract": "preparation",
            "contract_sha256": (
                ctrl._graph.get(
                    "phase3-tasks-lexicon"
                ).controller_state_contract.sha256
            ),
            "json_path": "$.echelon_result.attestation_probe",
            "validator": "detachment",
            "message": (
                "controller result preparation failed at "
                "$.echelon_result.attestation_probe (detachment)"
            ),
        }
        assert _RAW_ATTESTATION_SECRET not in json.dumps(blocked)

    def test_real_executor_detaches_before_schema_copy_protocols(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        protocol_calls: list[str] = []

        class ExplodingDeepcopy:
            def __deepcopy__(self, _memo):
                protocol_calls.append("__deepcopy__")
                raise RuntimeError(_RAW_ATTESTATION_SECRET)

        provider = _mock_provider()
        provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": {},
                "attestation_probe": ExplodingDeepcopy(),
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl, store = _controller(tmp_path, provider=provider)
        self._patch_run_guards(ctrl, monkeypatch)
        calls = self._patch_success_steps(ctrl, store, monkeypatch)

        result = ctrl.run_single_phase(
            "phase2-decide",
            "validate",
            "banzai",
        )

        assert result.status == "blocked"
        assert protocol_calls == []
        assert calls == []
        blocked = store.load()
        assert (
            blocked["controller_contract_error"]["json_path"]
            == "$.echelon_result.attestation_probe"
        )
        assert (
            blocked["controller_contract_error"]["validator"]
            == "detachment"
        )
        assert _RAW_ATTESTATION_SECRET not in json.dumps(blocked)

    def test_fresh_normal_mixed_governance_blocks_before_all_success_steps(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        self._patch_run_guards(ctrl, monkeypatch)
        executor = MagicMock()
        executor.execute.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "PASS",
                "state_updates": {"shadow_output_recovered": True},
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl._executors["agent"] = executor
        monkeypatch.setattr(
            ctrl,
            "_controller_enrichment",
            lambda *_: ControllerEnrichment(
                updates={
                    "feasibility_structural_pass": "not-boolean",
                    "feasibility_structural_attempts": 0,
                },
            ),
        )
        calls = self._patch_success_steps(ctrl, store, monkeypatch)

        result = ctrl.run(
            "msg",
            "banzai",
            next_phase_override="phase2-decide",
        )

        assert result.status == "blocked"
        assert result.phase == "phase2-decide"
        assert calls == []
        assert store.load()["completed_phases"] == []
        assert "shadow_output_recovered" not in store.load()

    def test_manual_execution_blocks_before_all_success_steps(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        self._patch_run_guards(ctrl, monkeypatch)
        executor = MagicMock()
        executor.execute.return_value = self._tasks_result("not-boolean")
        ctrl._executors["deterministic_lexicon"] = executor
        calls = self._patch_success_steps(ctrl, store, monkeypatch)

        result = ctrl.run_single_phase(
            "phase3-tasks-lexicon",
            "validate",
            "banzai",
        )

        assert result.status == "blocked"
        assert result.phase == "phase3-tasks-lexicon"
        assert calls == []
        assert store.load()["completed_phases"] == []

    def test_manual_routing_construction_failure_blocks_before_product_publication_or_success(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        self._patch_run_guards(ctrl, monkeypatch)
        executor = MagicMock()
        executor.execute.return_value = self._tasks_result(True)
        ctrl._executors["deterministic_lexicon"] = executor
        calls: list[str] = []

        def reject_route(*_args, **_kwargs):
            calls.append("routing")
            raise ControllerStateContractViolation(
                "provider-secret-must-not-leak",
                contract="routing",
                json_path="$.state_updates.manual_phase_runs",
                validator="ownership",
            )

        monkeypatch.setattr(
            ctrl,
            "_coordinate_transition_routing",
            reject_route,
        )
        monkeypatch.setattr(
            ctrl,
            "_prepare_external_phase_effects",
            lambda *_args, **_kwargs: calls.append("stage"),
        )
        monkeypatch.setattr(
            store,
            "advance",
            lambda *_args, **_kwargs: calls.append("advance"),
        )
        monkeypatch.setattr(
            ctrl,
            "_apply_declared_phase_timing_transition",
            lambda *_: calls.append("timing"),
        )
        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            lambda *_: calls.append("checkpoint"),
        )

        result = ctrl.run_single_phase(
            "phase3-tasks-lexicon",
            "validate",
            "banzai",
        )
        blocked = store.load()

        assert result.status == "blocked"
        assert result.phase == "phase3-tasks-lexicon"
        assert calls == ["stage", "routing"]
        assert blocked["completed_phases"] == []
        assert blocked["last_dispatch"] is None
        assert blocked["controller_contract_error"] == {
            "phase_id": "phase3-tasks-lexicon",
            "contract": "routing",
            "contract_sha256": (
                ctrl._graph.get(
                    "phase3-tasks-lexicon"
                ).controller_state_contract.sha256
            ),
            "json_path": "$.state_updates.manual_phase_runs",
            "validator": "ownership",
            "message": (
                "routing decision construction failed at "
                "$.state_updates.manual_phase_runs (ownership)"
            ),
        }
        assert "provider-secret-must-not-leak" not in json.dumps(blocked)

    def test_contract_failure_resume_retries_same_deterministic_phase_and_clears_after_advance(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        self._patch_run_guards(ctrl, monkeypatch)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase3-tasks-lexicon",
        )
        state = store.load()
        state["completed_phases"] = ["phase1-what"]
        store.save(state)
        executor = MagicMock()
        executor.execute.return_value = self._tasks_result("not-boolean")
        ctrl._executors["deterministic_lexicon"] = executor

        first = ctrl.run("msg", "banzai")

        assert first.status == "blocked"
        assert store.load()["completed_phases"] == ["phase1-what"]
        assert "controller_contract_error" in store.load()

        calls: list[str] = []
        executor.execute.return_value = self._tasks_result(True)
        original_prepare = ctrl._prepare_phase_result_or_block
        original_route = ctrl._coordinate_transition_routing
        original_advance = store.advance

        def record_prepare(*args):
            calls.append("prepare")
            return original_prepare(*args)

        def record_advance(*args, **kwargs):
            receipt = original_advance(*args, **kwargs)
            calls.append("advance")
            return receipt

        def record_route(*args, **kwargs):
            calls.append("routing")
            return original_route(*args, **kwargs)

        monkeypatch.setattr(ctrl, "_prepare_phase_result_or_block", record_prepare)
        monkeypatch.setattr(
            ctrl,
            "_prepare_external_phase_effects",
            lambda *_args, **_kwargs: calls.append("stage"),
        )
        monkeypatch.setattr(
            ctrl,
            "_coordinate_transition_routing",
            record_route,
        )
        monkeypatch.setattr(
            ctrl,
            "_apply_declared_phase_timing_transition",
            lambda *_: calls.append("timing"),
        )
        monkeypatch.setattr(store, "advance", record_advance)
        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            lambda *_: calls.append("checkpoint") or False,
        )

        resumed = ctrl.run_single_phase(
            "phase3-tasks-lexicon",
            "msg",
            "banzai",
        )
        resumed_state = store.load()

        assert resumed.status == "running"
        assert calls == [
            "prepare",
            "stage",
            "routing",
            "advance",
        ]
        assert resumed_state["phase"] == "phase3-understanding"
        assert resumed_state["completed_phases"] == [
            "phase1-what",
            "phase3-tasks-lexicon",
        ]
        assert "controller_contract_error" not in resumed_state

    def test_successful_self_loop_receipt_clears_prior_diagnostic(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        self._patch_run_guards(ctrl, monkeypatch)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase2-decide",
        )
        prior_dispatch = {
            "phase_id": "phase2-decide",
            "verdict": "PASS",
            "completed_at": "2026-07-23T00:00:00+00:00",
        }
        state = store.load()
        state["last_dispatch"] = deepcopy(prior_dispatch)
        state["completed_phases"] = ["phase2-decide"]
        state["controller_contract_error"] = {"prior": "diagnostic"}
        store.save(state)
        executor = MagicMock()
        executor.execute.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "PASS",
                "state_updates": {},
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl._executors["agent"] = executor
        monkeypatch.setattr(
            ctrl,
            "_controller_enrichment",
            lambda *_: ControllerEnrichment(
                updates={"feasibility_verdict": "PASS"},
                routing_override="phase2-decide",
            ),
        )
        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            lambda *_: False,
        )

        result = ctrl.run_single_phase(
            "phase2-decide",
            "msg",
            "banzai",
        )
        final = store.load()

        assert result.status == "running"
        assert "controller_contract_error" not in final
        assert final["last_dispatch"] != prior_dispatch
        assert final["phase"] == "phase2-decide"

    @pytest.mark.parametrize(
        ("route_flag", "expected_increment"),
        [(False, True), (True, False)],
        ids=["first-destination-match-increments", "later-same-destination-does-not"],
    )
    def test_duplicate_destination_uses_action_from_actual_first_match(
        self,
        tmp_path: Path,
        route_flag: bool,
        expected_increment: bool,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "duplicate-action")
        node = PhaseNode(
            id="duplicate-action",
            type="agent",
            allowed_state_updates=["route_flag"],
            transitions=[
                {
                    "to": "shared-destination",
                    "condition": "NOT route_flag",
                    "action": "increment_iteration",
                },
                {
                    "to": "shared-destination",
                    "condition": "always",
                },
            ],
        )
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(
            node,
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {"route_flag": route_flag},
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            ),
            snapshot,
        )

        decision = ctrl._coordinate_transition_routing(
            node,
            prepared,
            snapshot,
        )
        store.advance(
            node.id,
            decision.to_phase,
            decision,
        )

        assert decision.to_phase == "shared-destination"
        assert store.load()["iteration"] == int(expected_increment)

    def test_increment_and_receipt_precede_timing_and_checkpoint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        self._patch_run_guards(ctrl, monkeypatch)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase3-tasks-lexicon",
        )
        executor = MagicMock()
        executor.execute.return_value = self._tasks_result(
            False,
            action="repair",
        )
        ctrl._executors["deterministic_lexicon"] = executor
        calls: list[str] = []
        original_prepare = ctrl._prepare_phase_result_or_block
        original_route = ctrl._coordinate_transition_routing
        original_advance = store.advance

        def record_prepare(*args):
            calls.append("prepare")
            return original_prepare(*args)

        def record_route(*args, **kwargs):
            calls.append("routing")
            return original_route(*args, **kwargs)

        def record_advance(*args, **kwargs):
            receipt = original_advance(*args, **kwargs)
            calls.append("advance")
            return receipt

        def record_post_commit(step: str):
            state = store.load()
            assert state["iteration"] == 1
            assert state["phase"] == "phase3-plan"
            assert (
                state["last_dispatch"]["controller_contract"]
                == "tasks_lexicon"
            )
            calls.append(step)

        monkeypatch.setattr(ctrl, "_prepare_phase_result_or_block", record_prepare)
        monkeypatch.setattr(
            ctrl,
            "_prepare_external_phase_effects",
            lambda *_args, **_kwargs: calls.append("stage"),
        )
        monkeypatch.setattr(ctrl, "_coordinate_transition_routing", record_route)
        monkeypatch.setattr(store, "advance", record_advance)
        monkeypatch.setattr(
            ctrl,
            "_apply_declared_phase_timing_transition",
            lambda *_: record_post_commit("timing"),
        )
        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            lambda *_: record_post_commit("checkpoint") or False,
        )

        ctrl.run_single_phase(
            "phase3-tasks-lexicon",
            "msg",
            "banzai",
        )

        assert calls == [
            "prepare",
            "stage",
            "routing",
            "advance",
        ]
        assert store.load()["last_dispatch"][
            "post_dispatch_complete"
        ] is True

    def test_state_advance_failure_blocks_without_timing_or_checkpoint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        self._patch_run_guards(ctrl, monkeypatch)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase3-tasks-lexicon",
        )
        before = store.load()
        executor = MagicMock()
        executor.execute.return_value = self._tasks_result(True)
        ctrl._executors["deterministic_lexicon"] = executor
        calls: list[str] = []

        def fail_advance(*_args, **_kwargs):
            raise StateAdvanceError(
                "rejected-secret-value",
                json_path="$.prepared_result.ownership",
                validator="ownership",
            )

        monkeypatch.setattr(store, "advance", fail_advance)
        monkeypatch.setattr(
            ctrl,
            "_apply_declared_phase_timing_transition",
            lambda *_: calls.append("timing"),
        )
        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            lambda *_: calls.append("checkpoint"),
        )

        result = ctrl.run("msg", "banzai")
        blocked = store.load()

        assert result.status == "blocked"
        assert blocked["phase"] == "phase3-tasks-lexicon"
        assert blocked["completed_phases"] == before["completed_phases"]
        assert blocked["last_dispatch"] == before["last_dispatch"]
        assert (
            blocked["blocked_reason"]
            == "controller_state_contract_validation_failed"
        )
        assert blocked["controller_contract_error"] == {
            "phase_id": "phase3-tasks-lexicon",
            "contract": "tasks_lexicon",
            "contract_sha256": (
                ctrl._graph.get(
                    "phase3-tasks-lexicon"
                ).controller_state_contract.sha256
            ),
            "json_path": "$.prepared_result.ownership",
            "validator": "ownership",
            "message": (
                "state advance failed at "
                "$.prepared_result.ownership (ownership)"
            ),
        }
        assert "rejected-secret-value" not in json.dumps(blocked)
        assert calls == []

    def test_advance_failure_diagnostic_never_rolls_back_published_state(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase3-tasks-lexicon",
        )
        published = store.load()
        published["phase"] = "phase3-understanding"
        published["unrelated_concurrent_update"] = {"preserve": True}
        store.save(published)
        node = ctrl._graph.get("phase3-tasks-lexicon")

        ctrl._block_after_state_advance_failure(
            node,
            node.id,
            StateAdvanceError(
                "late receipt failure",
                json_path="$.last_dispatch",
                validator="receipt",
            ),
        )

        after = store.load()
        assert after["phase"] == "phase3-understanding"
        assert after["unrelated_concurrent_update"] == {"preserve": True}

    def test_missing_advance_receipt_is_not_treated_as_success(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        self._patch_run_guards(ctrl, monkeypatch)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase3-tasks-lexicon",
        )
        executor = MagicMock()
        executor.execute.return_value = self._tasks_result(True)
        ctrl._executors["deterministic_lexicon"] = executor
        calls: list[str] = []
        monkeypatch.setattr(store, "advance", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            ctrl,
            "_apply_declared_phase_timing_transition",
            lambda *_: calls.append("timing"),
        )
        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            lambda *_: calls.append("checkpoint"),
        )

        result = ctrl.run("msg", "banzai")

        assert result.status == "blocked"
        assert result.phase == "phase3-tasks-lexicon"
        assert store.load()["controller_contract_error"]["validator"] == "receipt"
        assert calls == []

    @pytest.mark.parametrize(
        "forge_receipt",
        [
            lambda receipt: replace(receipt, from_phase="forged-from"),
            lambda receipt: replace(receipt, to_phase="forged-to"),
            lambda receipt: replace(
                receipt,
                controller_contract="forged-contract",
            ),
            lambda receipt: replace(
                receipt,
                controller_contract_sha256="f" * 64,
            ),
            lambda receipt: replace(
                receipt,
                completed_at="2026-07-23T00:00:00+00:00",
            ),
            lambda receipt: replace(receipt, conditional_skip=True),
        ],
        ids=[
            "from-phase",
            "to-phase",
            "contract",
            "contract-digest",
            "completion-identity",
            "conditional-skip",
        ],
    )
    def _obsolete_forged_typed_receipt_restores_pre_advance_state_and_blocks(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        forge_receipt,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        self._patch_run_guards(ctrl, monkeypatch)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase3-tasks-lexicon",
        )
        before = store.load()
        executor = MagicMock()
        executor.execute.return_value = self._tasks_result(True)
        ctrl._executors["deterministic_lexicon"] = executor
        original_advance = store.advance
        calls: list[str] = []

        def return_forged_receipt(*args, **kwargs):
            return forge_receipt(original_advance(*args, **kwargs))

        monkeypatch.setattr(store, "advance", return_forged_receipt)
        monkeypatch.setattr(
            ctrl,
            "_apply_declared_phase_timing_transition",
            lambda *_: calls.append("timing"),
        )
        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            lambda *_: calls.append("checkpoint"),
        )

        result = ctrl.run("msg", "banzai")
        blocked = store.load()

        assert result.status == "blocked"
        assert blocked["phase"] == before["phase"]
        assert blocked["completed_phases"] == before["completed_phases"]
        assert blocked["last_dispatch"] == before["last_dispatch"]
        assert blocked["iteration"] == before["iteration"]
        assert blocked["controller_contract_error"]["validator"] == "receipt"
        assert calls == []

    @pytest.mark.parametrize(
        "forge_skip_identity",
        ["receipt", "persisted-marker"],
    )
    def _obsolete_conditional_skip_identity_forgery_blocks_before_success_effects(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        forge_skip_identity: str,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        original_advance = store.advance
        calls: list[str] = []

        def forge_conditional_skip(*args, **kwargs):
            receipt = original_advance(*args, **kwargs)
            if forge_skip_identity == "receipt":
                return replace(receipt, conditional_skip=False)
            state = store.load()
            state["last_dispatch"].pop("conditional_skip", None)
            store.save(state)
            return receipt

        monkeypatch.setattr(store, "advance", forge_conditional_skip)
        monkeypatch.setattr(
            ctrl,
            "_apply_declared_phase_timing_transition",
            lambda *_: calls.append("timing"),
        )
        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            lambda *_: calls.append("checkpoint"),
        )

        result = ctrl.run_single_phase(
            "phase1-modeler",
            "msg",
            "banzai",
        )
        blocked = store.load()

        assert result.status == "blocked"
        assert blocked["phase"] == "phase1-modeler"
        assert blocked["completed_phases"] == []
        assert blocked["last_dispatch"] is None
        assert blocked["controller_contract_error"]["validator"] == "receipt"
        assert calls == []

    def _obsolete_typed_receipt_without_persisted_dispatch_is_rejected(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase3-tasks-lexicon",
        )
        node = ctrl._graph.get("phase3-tasks-lexicon")
        prepared = ctrl._prepare_phase_result(
            node,
            self._tasks_result(True),
        )
        monkeypatch.setattr(
            store,
            "advance",
            lambda *_args, **_kwargs: AdvanceReceipt(
                from_phase=node.id,
                to_phase="phase3-understanding",
                completed_at=datetime.now(timezone.utc).isoformat(),
                controller_contract=prepared.controller_contract_name,
                controller_contract_sha256=(
                    prepared.controller_contract_sha256
                ),
                conditional_skip=False,
            ),
        )

        receipt = ctrl._advance_prepared_result_or_block(
            node,
            node.id,
            "phase3-understanding",
            prepared,
        )

        assert receipt is None
        diagnostic = store.load()["controller_contract_error"]
        assert diagnostic["validator"] == "receipt"
        assert diagnostic["json_path"] == "$.last_dispatch"

    def _obsolete_typed_but_stale_self_loop_receipt_is_rejected(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "phase2-decide")
        node = ctrl._graph.get("phase2-decide")
        monkeypatch.setattr(
            ctrl,
            "_controller_enrichment",
            lambda *_: ControllerEnrichment(
                updates={
                    "feasibility_structural_pass": False,
                    "feasibility_structural_attempts": 1,
                },
            ),
        )
        prepared = ctrl._prepare_phase_result(
            node,
            SquadAgentResult(
                exit_code=0,
                echelon_result={"verdict": "PASS", "state_updates": {}},
                raw_output="",
                duration_ms=0,
                timed_out=False,
            ),
        )
        completed_at = "2026-07-23T00:00:00+00:00"
        stale_receipt = AdvanceReceipt(
            from_phase=node.id,
            to_phase=node.id,
            completed_at=completed_at,
            controller_contract=prepared.controller_contract_name,
            controller_contract_sha256=prepared.controller_contract_sha256,
            conditional_skip=False,
        )
        state = store.load()
        state["last_dispatch"] = {
            "phase_id": node.id,
            "verdict": prepared.verdict,
            "completed_at": completed_at,
            "controller_contract": prepared.controller_contract_name,
            "controller_contract_sha256": (
                prepared.controller_contract_sha256
            ),
            "controller_normalized": bool(prepared.normalized_paths),
            "conditional_skip": False,
        }
        store.save(state)
        prior_dispatch = deepcopy(store.load()["last_dispatch"])
        monkeypatch.setattr(
            store,
            "advance",
            lambda *_args, **_kwargs: stale_receipt,
        )

        receipt = ctrl._advance_prepared_result_or_block(
            node,
            node.id,
            node.id,
            prepared,
        )

        assert receipt is None
        blocked = store.load()
        assert blocked["last_dispatch"] == prior_dispatch
        assert blocked["controller_contract_error"]["validator"] == "receipt"

    def test_manual_success_advances_before_timing_and_checkpoint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        self._patch_run_guards(ctrl, monkeypatch)
        executor = MagicMock()
        executor.execute.return_value = self._tasks_result(True)
        ctrl._executors["deterministic_lexicon"] = executor
        calls: list[str] = []
        original_advance = store.advance

        def record_advance(*args, **kwargs):
            calls.append("advance")
            return original_advance(*args, **kwargs)

        monkeypatch.setattr(store, "advance", record_advance)
        monkeypatch.setattr(
            ctrl,
            "_apply_declared_phase_timing_transition",
            lambda *_: calls.append("timing"),
        )
        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            lambda *_: calls.append("checkpoint") or False,
        )

        result = ctrl.run_single_phase(
            "phase3-tasks-lexicon",
            "validate",
            "banzai",
        )

        assert calls == ["advance"]
        assert result.phase == "phase3-understanding"
        assert store.load()["last_dispatch"]["manual_phase_run"] is True
        assert store.load()["last_dispatch"]["conditional_skip"] is False
        assert store.load()["last_dispatch"][
            "post_dispatch_complete"
        ] is True

    def test_valid_blocked_understanding_is_prepared_before_executor_block(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        self._patch_run_guards(ctrl, monkeypatch)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-understanding",
        )
        executor = MagicMock()
        executor.execute.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "BLOCKED",
                "state_updates": {
                    "blocked_reason": "temporary analysis failure",
                    "understanding_evidence": {
                        "phase": "phase1-why2",
                        "iteration": 0,
                        "status": "error",
                        "path": "/tmp/understanding-error.json",
                        "digest": None,
                        "pass": None,
                        "failing_gates": [],
                        "error": "temporary analysis failure",
                    },
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        ctrl._executors["deterministic_understanding"] = executor
        state = store.load()
        state["controller_contract_error"] = {"prior": "diagnostic"}
        state["recovery_instruction"] = {
            "schema_version": 1,
            "kind": "sync_runtime_then_retry",
            "reason_code": "controller_state_contract_validation_failed",
            "phase": "phase1-understanding",
            "requires_human_input": False,
        }
        store.save(state)
        calls: list[str] = []
        original_prepare = ctrl._prepare_phase_result_or_block
        original_block = ctrl._block_after_executor_failure

        def record_prepare(*args):
            calls.append("prepare")
            return original_prepare(*args)

        def record_block(*args, **kwargs):
            calls.append("block")
            return original_block(*args, **kwargs)

        monkeypatch.setattr(ctrl, "_prepare_phase_result_or_block", record_prepare)
        monkeypatch.setattr(ctrl, "_block_after_executor_failure", record_block)
        monkeypatch.setattr(
            ctrl,
            "_apply_product_input_updates",
            lambda *_: calls.append("product"),
        )
        monkeypatch.setattr(
            ctrl,
            "_coordinate_transition_routing",
            lambda *_: calls.append("routing"),
        )
        monkeypatch.setattr(
            ctrl,
            "_apply_declared_phase_timing_transition",
            lambda *_: calls.append("timing"),
        )
        monkeypatch.setattr(
            store,
            "advance",
            lambda *_args, **_kwargs: calls.append("advance"),
        )
        monkeypatch.setattr(
            ctrl,
            "_checkpoint_successful_phase",
            lambda *_: calls.append("checkpoint"),
        )

        result = ctrl.run("msg", "banzai")
        blocked = store.load()

        assert result.status == "blocked"
        assert calls == ["prepare", "block"]
        assert blocked["phase"] == "phase1-understanding"
        assert (
            blocked["blocked_reason"] == "temporary analysis failure"
        )
        assert "controller_contract_error" not in blocked
        assert "recovery_instruction" not in blocked
        assert blocked["understanding_evidence"]["status"] == "error"
        assert "phase1-understanding" not in blocked["completed_phases"]

    def test_mixed_governance_failure_does_not_apply_provider_updates(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "phase2-decide")
        state = store.load()
        state["completed_phases"] = ["phase1-what"]
        store.save(state)
        node = ctrl._graph.get("phase2-decide")
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "PASS",
                "state_updates": {"shadow_output_recovered": True},
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        monkeypatch.setattr(
            ctrl,
            "_controller_enrichment",
            lambda *_: ControllerEnrichment(
                updates={
                    "feasibility_structural_pass": "governance-secret",
                    "feasibility_structural_attempts": 0,
                },
            ),
        )

        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result_or_block(
            node,
            result,
            snapshot,
        )
        blocked = store.load()

        assert prepared is None
        assert blocked["phase"] == "phase2-decide"
        assert blocked["completed_phases"] == ["phase1-what"]
        assert "shadow_output_recovered" not in blocked
        assert (
            blocked["controller_contract_error"]["contract"]
            == "feasibility_authoring_verdict"
        )
        assert "governance-secret" not in json.dumps(
            blocked["controller_contract_error"]
        )

    def test_allowed_empty_skip_uses_fail_closed_preparation_boundary(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        calls: list[str] = []
        original_prepare = ctrl._prepare_phase_result_or_block

        def record_prepare(node, result, snapshot):
            calls.append(node.id)
            return original_prepare(node, result, snapshot)

        monkeypatch.setattr(ctrl, "_prepare_phase_result_or_block", record_prepare)

        result = ctrl.run_single_phase("phase1-modeler", "msg", "banzai")

        assert result.status == "running"
        assert calls == ["phase1-modeler"]
        assert store.load()["phase"] == "phase1-tracker"


class TestProductInputMappingRepair:
    def test_dispatch_reason_is_controller_owned(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-plan", max_iterations=5)
        assert ctrl._dispatch_reason("phase3-plan", 1) == "initial"
        assert ctrl._dispatch_reason("phase3-plan", 2) == "planned_iteration"
        assert ctrl._dispatch_reason("phase1-what", 2) == "semantic_repair"
        state = store.load()
        state["product_input_mapping_repair"] = {"protocol_version": 2}
        store.save(state)
        assert ctrl._dispatch_reason("phase3-plan", 2) == "deterministic_repair"

    def test_blocker_event_survives_mutable_state_rewrite(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-plan", max_iterations=5)
        snapshot = store.capture_routing_snapshot(
            expected_phase="phase3-plan"
        )
        ctrl._block_after_executor_failure(
            "phase3-plan",
            "agent_exit_code_1",
            SquadAgentResult(1, None, "", 0, False),
            snapshot=snapshot,
        )
        state = store.load()
        state["blocked_reason"] = "rewritten"
        store.save(state)
        events = [json.loads(line) for line in ctrl._telemetry_store.events_path.read_text().splitlines()]
        assert events[-1]["type"] == "blocker"
        assert events[-1]["reason"] == "agent_exit_code_1"

    def test_new_executor_failure_clears_prior_recovery_generation(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "banzai",
            "msg",
            0,
            "phase3-plan",
            max_iterations=5,
        )
        state = store.load()
        state["controller_contract_error"] = {"prior": "diagnostic"}
        state["recovery_instruction"] = {
            "schema_version": 1,
            "kind": "retry_phase",
            "reason_code": "missing_phase_outputs",
            "phase": "phase1-what",
            "requires_human_input": False,
        }
        state["missing_outputs"] = ["requirements-overview.md"]
        state["phase_output_recovery"] = {
            "phase": "phase1-what",
            "missing_outputs": ["requirements-overview.md"],
            "prior_state_updates": {},
        }
        store.save(state)
        snapshot = store.capture_routing_snapshot(
            expected_phase="phase3-plan"
        )

        ctrl._block_after_executor_failure(
            "phase3-plan",
            "agent_exit_code_1",
            SquadAgentResult(1, None, "", 0, False),
            snapshot=snapshot,
        )

        blocked = store.load()
        assert blocked["blocked_reason"] == "agent_exit_code_1"
        assert "controller_contract_error" not in blocked
        assert "recovery_instruction" not in blocked
        assert "missing_outputs" not in blocked
        assert "phase_output_recovery" not in blocked

    def test_executor_retry_retires_unrelated_resolved_decision_audit(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "banzai",
            "msg",
            0,
            "phase3-how",
            max_iterations=5,
        )
        policy = HumanInputPolicy(
            source_kind="human_gate",
            producer_id="test-checkpoint",
            reason_code="test_approval_required",
            classification="material",
            semi_policy="require_human",
            resolution_handler="gate_outcome",
            allow_free_text=False,
            allowed_phase_ids=frozenset({"phase3-how"}),
            allowed_target_phases=frozenset(
                {"phase3-how", "terminal-blocked"}
            ),
            context_state_keys=("phase",),
            context_paths=(),
            options=(
                HumanInputOption(
                    id="approve",
                    label="Approve",
                    description="Continue.",
                    recommended=True,
                    risk_level="low",
                    next_phase="phase3-how",
                    outcome="approved",
                ),
                HumanInputOption(
                    id="reject",
                    label="Reject",
                    description="Stop.",
                    recommended=False,
                    risk_level="medium",
                    next_phase="terminal-blocked",
                    outcome="rejected",
                ),
            ),
            recommendation_mode="static",
        )
        request = HumanInputPolicyRegistry((policy,)).prepare(
            source_kind="human_gate",
            producer_id="test-checkpoint",
            phase_id="phase3-how",
            reason_code="test_approval_required",
            question="Continue?",
            source_state_revision=store.load()["state_revision"],
        )
        awaiting = store.set_human_input_decision(
            request,
            initial_status="awaiting_human",
        )
        resolved = store.apply_human_input_state_resolution(
            awaiting["blocked_decision"]["id"],
            expected_state_revision=awaiting["state_revision"],
            resolution=HumanInputResolution(
                selected_option_id="approve",
                answer_text=None,
                resolved_by="COMMANDER",
                rationale="The checkpoint is current.",
                confidence="high",
            ),
            state_updates={"status": "running", "phase": "phase3-how"},
            state_removals=(),
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase="phase3-how"
        )

        assert ctrl._block_after_executor_failure(
            "phase3-how",
            "agent_blocked",
            SquadAgentResult(0, None, "", 0, False),
            snapshot=snapshot,
            recovery_instruction=retry_phase_recovery(
                "phase3-how",
                "agent_blocked",
            ),
        )

        blocked = store.load()
        assert blocked["status"] == "blocked"
        assert blocked["phase"] == "terminal-blocked"
        assert blocked["recovery_instruction"] == {
            "schema_version": 1,
            "kind": "retry_phase",
            "reason_code": "agent_blocked",
            "phase": "phase3-how",
            "requires_human_input": False,
        }
        assert "blocked_decision" not in blocked
        assert blocked["state_revision"] == resolved["state_revision"] + 1

    def test_stale_executor_failure_cannot_erase_winning_phase_or_dispatch(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "banzai",
            "msg",
            0,
            "phase1-discover",
            max_iterations=5,
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase="phase1-discover"
        )
        winner = store.load()
        winner["phase"] = "phase1-why1"
        winner["last_dispatch"] = {
            "dispatch_id": "winner",
            "phase_id": "phase1-discover",
        }
        winner["winner_marker"] = True
        store.save(winner)
        before = store.load()

        persisted = ctrl._block_after_executor_failure(
            "phase1-discover",
            "agent_exit_code_1",
            SquadAgentResult(1, None, "", 0, False),
            snapshot=snapshot,
        )

        assert persisted is False
        assert store.load() == before

    def test_analyzer_uses_controller_blocker_history_not_state(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-plan", max_iterations=5)
        result = SquadAgentResult(1, None, "", 0, False)
        first_snapshot = store.capture_routing_snapshot(
            expected_phase="phase3-plan"
        )
        ctrl._block_after_executor_failure(
            "phase3-plan",
            "agent_exit_code_1",
            result,
            snapshot=first_snapshot,
        )
        second_snapshot = store.capture_routing_snapshot(
            expected_phase="terminal-blocked"
        )
        ctrl._block_after_executor_failure(
            "phase3-plan",
            "agent_exit_code_1",
            result,
            snapshot=second_snapshot,
        )
        state = store.load()
        state["blocked_reason_history"] = []
        store.save(state)

        report = analyze_spec_run(store.squad_dir)

        assert report.workflow_metrics["repeated_blockers"] == {"agent_exit_code_1": 2}

    def test_plan_mapping_failure_is_requeued_with_controller_context(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-plan", max_iterations=5)
        snapshot = store.capture_routing_snapshot(
            expected_phase="phase3-plan"
        )

        repaired = ctrl._schedule_product_input_mapping_repair(
            "phase3-plan",
            "invalid product input task mappings: "
            "IN-REQ-1: unresolved disposition open_question",
            snapshot=snapshot,
        )

        state = store.load()
        assert repaired is True
        assert state["phase"] == "phase3-plan"
        assert state["status"] == "running"
        assert state["product_input_mapping_repair_attempts"] == 1
        assert state["product_input_mapping_repair"]["blockers"] == [
            "IN-REQ-1: unresolved disposition open_question"
        ]

    def test_stale_product_repair_cannot_rebase_onto_winning_phase(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "banzai",
            "msg",
            0,
            "phase3-plan",
            max_iterations=5,
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase="phase3-plan"
        )
        winner = store.load()
        winner["phase"] = "phase3-consensus"
        winner["last_dispatch"] = {
            "dispatch_id": "winner",
            "phase_id": "phase3-plan",
        }
        store.save(winner)
        before = store.load()

        repaired = ctrl._schedule_product_input_mapping_repair(
            "phase3-plan",
            "invalid product input task mappings: IN-REQ-1 unresolved",
            snapshot=snapshot,
        )

        assert repaired is False
        assert store.load() == before

    def test_stale_phase_a_readiness_failure_cannot_erase_winner(
        self,
        tmp_path: Path,
    ) -> None:
        from harness.phase_a_readiness import PhaseAReadinessResult

        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "banzai",
            "msg",
            0,
            "phase4-document",
            max_iterations=5,
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase="phase4-document"
        )
        winner = store.load()
        winner["phase"] = "done"
        winner["status"] = "done"
        winner["last_dispatch"] = {
            "dispatch_id": "winner",
            "phase_id": "phase4-document",
        }
        store.save(winner)
        before = store.load()

        persisted = ctrl._block_after_phase_a_readiness_failure(
            PhaseAReadinessResult(
                ready=False,
                blockers=["stale failure"],
                missing={},
                ready_spec_dir=None,
            ),
            snapshot=snapshot,
        )

        assert persisted is False
        assert store.load() == before

    def test_plan_mapping_repair_stops_after_bounded_attempts(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-plan", max_iterations=5)
        state = store.load()
        state["product_input_mapping_repair_attempts"] = 2
        state["product_input_mapping_repair"] = {"protocol_version": 2}
        store.save(state)
        snapshot = store.capture_routing_snapshot(
            expected_phase="phase3-plan"
        )

        repaired = ctrl._schedule_product_input_mapping_repair(
            "phase3-plan",
            "invalid product input task mappings: "
            "IN-REQ-1: unresolved disposition open_question",
            snapshot=snapshot,
        )

        assert repaired is False

    def test_outdated_mapping_repair_protocol_gets_a_fresh_budget(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        store.initialize("r", "banzai", "msg", 0, "phase3-plan", max_iterations=5)
        state = store.load()
        state["product_input_mapping_repair_attempts"] = 2
        state["product_input_mapping_repair"] = {"attempt": 2, "blockers": ["old"]}
        state["phase_dispatch_counts"] = {"phase3-plan": 4}
        store.save(state)
        snapshot = store.capture_routing_snapshot(
            expected_phase="phase3-plan"
        )

        repaired = ctrl._schedule_product_input_mapping_repair(
            "phase3-plan",
            "invalid product input task mappings: "
            "IN-REQ-1: unresolved disposition open_question",
            snapshot=snapshot,
        )

        state = store.load()
        assert repaired is True
        assert state["product_input_mapping_repair_attempts"] == 1
        assert state["product_input_mapping_repair"]["protocol_version"] == 2
        assert state["phase_dispatch_counts"]["phase3-plan"] == 0


class TestLexiconGateGuardDeterminism:
    """The lexicon-gate self-loop guards (phase3-plan tasks gate) must route
    deterministically via ConditionEvaluator — never punt to COMMANDER.

    Regression: a live run flagged the guard as referencing undefined state keys
    (lexicon_gate.*, tasks_lexicon_pass), making the condition indeterminate.
    Fix = NOT handler in ConditionEvaluator + merging the lexicon_gate config
    block into the eval state so `lexicon_gate.enabled` resolves.
    """

    @staticmethod
    def _result(
        updates: dict,
        *,
        verdict: str = "PASS",
    ) -> SquadAgentResult:
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": verdict, "state_updates": updates},
            raw_output="", duration_ms=0, timed_out=False,
        )

    def test_lexicon_derivation_requires_current_phase1_quality_prerequisite(
        self,
        tmp_path,
        monkeypatch,
    ):
        ctrl, store = _controller(tmp_path)
        state = store.load()
        state.update(
            {
                "phase": "phase1-lexicon-derive",
                "completed_phases": [
                    "phase1-what",
                    "phase1-understanding",
                    "phase1-why2",
                    "phase1-lexicon-derive",
                    "phase1-lexicon",
                ],
                "phase_dispatch_counts": {
                    "phase1-understanding": 1,
                    "phase1-why2": 1,
                    "phase1-lexicon-derive": 1,
                    "phase1-lexicon": 1,
                },
            }
        )
        store.save(state)
        monkeypatch.setattr(
            "harness.squad.has_current_phase1_quality_prerequisite",
            lambda *_args, **_kwargs: False,
            raising=False,
        )

        guarded = ctrl._guard_phase1_quality_evidence(
            "phase1-lexicon-derive"
        )

        assert guarded == "phase1-understanding"
        persisted = store.load()
        assert persisted["phase"] == "phase1-understanding"
        assert "phase1-why2" not in persisted["completed_phases"]
        assert "phase1-lexicon-derive" not in persisted["phase_dispatch_counts"]

    def test_current_phase1_quality_prerequisite_allows_lexicon_derivation(
        self,
        tmp_path,
        monkeypatch,
    ):
        ctrl, store = _controller(tmp_path)
        state = store.load()
        state["phase"] = "phase1-lexicon-derive"
        store.save(state)
        monkeypatch.setattr(
            "harness.squad.has_current_phase1_quality_prerequisite",
            lambda *_args, **_kwargs: True,
            raising=False,
        )

        assert (
            ctrl._guard_phase1_quality_evidence("phase1-lexicon-derive")
            == "phase1-lexicon-derive"
        )

    def test_quality_guard_rewinds_a_later_phase_with_invalid_debt_authority(
        self,
        tmp_path,
        monkeypatch,
    ):
        ctrl, store = _controller(tmp_path)
        state = store.load()
        state.update(
            {
                "phase": "phase3-plan",
                "spec_quality_debt_authorization": {
                    "status": "accepted_with_debt"
                },
                "spec_status": "accepted_with_debt",
            }
        )
        store.save(state)
        monkeypatch.setattr(
            "harness.squad.has_current_phase1_quality_prerequisite",
            lambda *_args, **_kwargs: False,
            raising=False,
        )

        assert (
            ctrl._guard_phase1_quality_evidence("phase3-plan")
            == "phase1-understanding"
        )
        invalidated = store.load()
        assert invalidated["phase"] == "phase1-understanding"
        assert "spec_quality_debt_authorization" not in invalidated
        assert "spec_status" not in invalidated

    def test_passing_why2_creates_controller_quality_certificate(
        self,
        tmp_path,
        monkeypatch,
    ):
        ctrl, _store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-why2")
        certificate = {
            "schema_version": 1,
            "status": "passed",
            "source_path": "specs/001/spec.md",
            "source_sha256": "a" * 64,
            "understanding_evidence": "runs/r/evidence/why2.json",
            "understanding_evidence_sha256": "b" * 64,
            "sage_phase": "phase1-why2",
        }
        assessment = squad_module.AuthoritativeQualityAssessment(
            numeric_pass=True,
            provider_verdict="PASS",
            sage_verdict="PASS",
            authoritative_issues=(),
            exact_routes=(),
            ordinary_pass=True,
            proportional_failure=False,
            hard_blockers=(),
        )
        monkeypatch.setattr(
            "harness.squad.build_legacy_phase1_quality_certificate",
            lambda *_args, **_kwargs: certificate,
        )
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "PASS",
                "state_updates": {
                    "evidence_resolution_status": "not_required",
                    "finding_routes": {"findings": []},
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        enrichment = ctrl._controller_enrichment(
            node,
            {
                "quality_scores": [{"pass": True}],
                "spec_authoring_mode": "perfectionist",
                "spec_dir": "specs/001",
            },
            result,
        )

        assert enrichment.updates["spec_quality_certificate"] == certificate

    def test_spec_and_lexicon_writes_invalidate_only_owned_quality_authority(
        self,
        tmp_path,
    ):
        ctrl, _store = _controller(tmp_path)
        done = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": {},
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        what = ctrl._controller_enrichment(
            ctrl._graph.get("phase1-what"),
            {},
            done,
        )
        derive = ctrl._controller_enrichment(
            ctrl._graph.get("phase1-lexicon-derive"),
            {},
            done,
        )

        assert "spec_quality_certificate" in what.state_removals
        assert "spec_quality_debt_authorization" in what.state_removals
        assert "spec_quality_certificate" not in derive.state_removals
        assert "spec_quality_debt_authorization" not in derive.state_removals
        assert {
            "lexicon_evaluation",
            "lexicon_pass",
            "lexicon_findings",
            "lexicon_report",
        }.issubset(what.state_removals)
        assert {
            "lexicon_evaluation",
            "lexicon_pass",
            "lexicon_findings",
            "lexicon_report",
        }.issubset(derive.state_removals)

    def test_current_debt_authorization_allows_lexicon_derivation(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
        assert ctrl.resume_with_human_input("continue_with_debt")

        assert (
            ctrl._guard_phase1_quality_evidence("phase1-lexicon-derive")
            == "phase1-lexicon-derive"
        )

    @pytest.mark.parametrize("tamper", ["source", "evidence", "decision", "debt"])
    def test_sealed_debt_publication_reauthenticates_before_apply_and_recovery(
        self,
        tmp_path: Path,
        tamper: str,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        active = tmp_path / "runs/run-test/specs/001-demo"
        active.mkdir(parents=True, exist_ok=True)
        _write_phase_a_build_inputs(active, prefix="accepted ", include_fr=True)
        spec_text = (active / "spec.md").read_text(encoding="utf-8")
        updates, why2 = _proportional_assessment_fixture(
            ctrl,
            store,
            0,
            spec_text=spec_text,
        )
        state = store.load()
        state.update(updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
        assert ctrl.resume_with_human_input("continue_with_debt")

        _mark_constitution_complete(tmp_path, store)
        published = tmp_path / "specs/001-demo"
        published.mkdir(parents=True)
        state = store.load()
        state.update(
            {
                "phase": "phase4-document",
                "status": "running",
                "published_spec_dir": "specs/001-demo",
            }
        )
        store.save(state)
        kb_report = tmp_path / "runs" / "r" / "kb-apply-report.yaml"
        kb_report.parent.mkdir(parents=True, exist_ok=True)
        kb_report.write_text("status: degraded\n", encoding="utf-8")
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        prepared = ctrl._prepare_external_phase_effects(
            result,
            "phase4-document",
            store.load(),
            manual_phase_run=False,
        )
        assert prepared is not None
        marker = _install_publication_marker(store, prepared)

        current = store.load()
        authorization = current["spec_quality_debt_authorization"]
        if tamper == "source":
            (active / "spec.md").write_text(
                spec_text + "\nchanged after sealing\n",
                encoding="utf-8",
            )
        elif tamper == "evidence":
            evidence = Path(authorization["understanding_evidence"])
            if not evidence.is_absolute():
                evidence = tmp_path / evidence
            evidence.write_bytes(evidence.read_bytes() + b"\n")
        elif tamper == "decision":
            mutated_authorization = dict(authorization)
            decision = dict(mutated_authorization["resolved_decision"])
            decision["question"] = "Mutated after publication sealing."
            mutated_authorization["resolved_decision"] = decision
            current["spec_quality_debt_authorization"] = mutated_authorization
            store.save(current)
        else:
            debt = Path(authorization["debt_artifact"])
            if not debt.is_absolute():
                debt = tmp_path / debt
            debt.write_bytes(debt.read_bytes() + b"\n")

        assert ctrl._publish_and_finalize(prepared, marker) is False
        assert not (published / "quality-debt.json").exists()
        assert PENDING_EXTERNAL_PUBLICATION_KEY in store.load()

        del ctrl
        fresh, _ = _controller(tmp_path)
        assert fresh._recover_pending_external_publication() is False
        assert not (published / "quality-debt.json").exists()
        assert PENDING_EXTERNAL_PUBLICATION_KEY in store.load()

    def test_phase3_specialists_receive_pinned_debt_without_graph_path_mutation(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
        assert ctrl.resume_with_human_input("continue_with_debt")
        state = store.load()
        state["guardian_mode"] = "always_on"
        store.save(state)

        graph_node = ctrl._graph.get("phase3-specialists")
        original_agent_contexts = copy.deepcopy(graph_node.agents)
        dispatched = ctrl._materialize_controller_phase_inputs(graph_node)
        authorization = store.load()["spec_quality_debt_authorization"]
        debt_path = tmp_path / authorization["debt_artifact"]
        accepted_bytes = debt_path.read_bytes()
        debt_path.write_text('{"status":"tampered"}\n', encoding="utf-8")
        ctrl._provider.exec_agent.reset_mock()
        ctrl._provider.exec_agent.return_value = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        ctrl._executors["conditional_sequential"].execute(dispatched, store)

        prompts = [call.args[1] for call in ctrl._provider.exec_agent.call_args_list]
        assert prompts
        assert all(accepted_bytes.decode("utf-8") in prompt for prompt in prompts)
        assert all('"status":"tampered"' not in prompt for prompt in prompts)
        assert graph_node.agents == original_agent_contexts
        assert graph_node.controller_context == ""

    def test_invalid_debt_authorization_routes_through_understanding_fail_closed(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
        assert ctrl.resume_with_human_input("continue_with_debt")
        debt_path = tmp_path / "runs/run-test/specs/001-demo/quality-debt.json"
        debt_path.write_bytes(debt_path.read_bytes() + b"\n")

        assert (
            ctrl._guard_phase1_quality_evidence("checkpoint-assess")
            == "phase1-understanding"
        )
        invalidated = store.load()
        assert invalidated["phase"] == "phase1-understanding"
        assert "spec_quality_debt_authorization" not in invalidated
        assert debt_path.exists()

    def test_what_amendment_removes_debt_only_after_recoverable_state_authority(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
        assert ctrl.resume_with_human_input("continue_with_debt")

        debt_path = tmp_path / "runs/run-test/specs/001-demo/quality-debt.json"
        spec_path = tmp_path / "runs/run-test/specs/001-demo/spec.md"
        state = store.load()
        state.update(
            {
                "phase": "phase1-what",
                "spec_quality_certificate": {"stale": True},
            }
        )
        store.save(state)
        spec_path.write_text("# Amended specification\n", encoding="utf-8")
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": {
                    "evidence_resolution_status": "not_required",
                },
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
        node = ctrl._graph.get("phase1-what")
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        decision = ctrl._coordinate_transition_routing(
            node,
            ctrl._prepare_phase_result(node, result, snapshot),
            snapshot,
        )

        before_authority = store.load()
        assert debt_path.exists()
        assert "spec_quality_debt_authorization" in before_authority
        assert "spec_quality_certificate" in before_authority

        assert ctrl._advance_prepared_result_or_block(node, decision) is not None
        amended = store.load()
        assert not debt_path.exists()
        assert "spec_quality_debt_authorization" not in amended
        assert "spec_quality_certificate" not in amended
        assert PENDING_CONTROLLER_COMPLETION_KEY not in amended

    def test_what_debt_removal_failure_recovers_before_downstream_dispatch(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
        assert ctrl.resume_with_human_input("continue_with_debt")

        debt_path = tmp_path / "runs/run-test/specs/001-demo/quality-debt.json"
        spec_path = tmp_path / "runs/run-test/specs/001-demo/spec.md"
        state = store.load()
        state["phase"] = "phase1-what"
        store.save(state)
        spec_path.write_text("# Amended specification\n", encoding="utf-8")
        real_effect = squad_module.apply_or_verify_proportional_quality_effect

        def fail_removal(*args: object, **kwargs: object) -> object:
            raise CompletionError("stage_io")

        monkeypatch.setattr(
            squad_module,
            "apply_or_verify_proportional_quality_effect",
            fail_removal,
        )
        node = ctrl._graph.get("phase1-what")
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        decision = ctrl._coordinate_transition_routing(
            node,
            ctrl._prepare_phase_result(
                node,
                SquadAgentResult(
                    exit_code=0,
                    echelon_result={
                        "verdict": "DONE",
                        "state_updates": {
                            "evidence_resolution_status": "not_required",
                        },
                    },
                    raw_output="",
                    duration_ms=0,
                    timed_out=False,
                ),
                snapshot,
            ),
            snapshot,
        )
        assert ctrl._advance_prepared_result_or_block(node, decision) is None

        pending = store.load()
        assert debt_path.exists()
        assert "spec_quality_debt_authorization" not in pending
        assert PENDING_CONTROLLER_COMPLETION_KEY in pending
        assert pending["blocked_reason"] == "controller_completion_pending"

        monkeypatch.setattr(
            squad_module,
            "apply_or_verify_proportional_quality_effect",
            real_effect,
        )
        recovered = ctrl._drain_pending_controller_completion()
        assert recovered.recovered is True
        assert not debt_path.exists()
        assert PENDING_CONTROLLER_COMPLETION_KEY not in store.load()

    def test_what_debt_removal_unlinks_owned_symlink_without_following_target(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
        assert ctrl.resume_with_human_input("continue_with_debt")

        spec_dir = tmp_path / "runs/run-test/specs/001-demo"
        debt_path = spec_dir / "quality-debt.json"
        debt_path.unlink()
        target = spec_dir.parent.parent / "src" / "important.py"
        target.parent.mkdir()
        target.write_bytes(b"important bytes\n")
        debt_path.symlink_to("../../src/important.py")
        state = store.load()
        state["phase"] = "phase1-what"
        store.save(state)
        (spec_dir / "spec.md").write_text(
            "# Amended specification\n",
            encoding="utf-8",
        )

        next_phase = _coordinate_prepared_result(
            ctrl,
            ctrl._graph.get("phase1-what"),
            SquadAgentResult(
                exit_code=0,
                echelon_result={
                    "verdict": "DONE",
                    "state_updates": {
                        "evidence_resolution_status": "not_required",
                    },
                },
                raw_output="",
                duration_ms=0,
                timed_out=False,
            ),
        )

        assert next_phase == "phase1-understanding"
        assert not debt_path.is_symlink()
        assert target.read_bytes() == b"important bytes\n"
        assert "spec_quality_debt_authorization" not in store.load()
        assert PENDING_CONTROLLER_COMPLETION_KEY not in store.load()

    def test_guard_then_fresh_debt_resolution_replaces_exact_stale_artifact(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _start_proportional_quality_loop(
            tmp_path,
            automatic_consumed=3,
        )
        updates, why2 = _proportional_assessment_fixture(ctrl, store, 0)
        state = store.load()
        state.update(updates)
        store.save(state)
        _coordinate_prepared_result(ctrl, ctrl._graph.get("phase1-why2"), why2)
        assert ctrl.resume_with_human_input("continue_with_debt")

        debt_path = tmp_path / "runs/run-test/specs/001-demo/quality-debt.json"
        stale = debt_path.read_bytes() + b"\n"
        debt_path.write_bytes(stale)
        assert (
            ctrl._guard_phase1_quality_evidence("checkpoint-assess")
            == "phase1-understanding"
        )
        assert debt_path.read_bytes() == stale
        assert "spec_quality_debt_authorization" not in store.load()

        fresh_updates, fresh_why2 = _proportional_assessment_fixture(
            ctrl,
            store,
            1,
            score=0.61,
        )
        assert (
            _route_understanding_assessment(ctrl, store, fresh_updates)
            == "phase1-why2"
        )
        assert (
            _coordinate_prepared_result(
                ctrl,
                ctrl._graph.get("phase1-why2"),
                fresh_why2,
            )
            == "terminal-blocked"
        )

        real_effect = squad_module.apply_or_verify_proportional_quality_effect
        failed_after_write = False

        def write_then_fail_once(*args: object, **kwargs: object) -> object:
            nonlocal failed_after_write
            receipt = real_effect(*args, **kwargs)
            if not failed_after_write:
                failed_after_write = True
                raise CompletionError("stage_io")
            return receipt

        monkeypatch.setattr(
            squad_module,
            "apply_or_verify_proportional_quality_effect",
            write_then_fail_once,
        )

        assert ctrl.resume_with_human_input("continue_with_debt") is False
        pending = store.load()
        assert PENDING_CONTROLLER_COMPLETION_KEY in pending
        assert debt_path.read_bytes() != stale

        monkeypatch.setattr(
            squad_module,
            "apply_or_verify_proportional_quality_effect",
            real_effect,
        )
        recovered = ctrl._drain_pending_controller_completion()

        assert recovered.recovered is True
        accepted = store.load()
        assert PENDING_CONTROLLER_COMPLETION_KEY not in accepted
        assert accepted["spec_quality_debt_authorization"][
            "debt_artifact_sha256"
        ] == hashlib.sha256(debt_path.read_bytes()).hexdigest()

    def test_spec_lexicon_node_certifies_valid_artifact_without_provider(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        node = ctrl._graph.get("phase1-lexicon")
        store.initialize("r", "greenfield", "msg", 0, node.id)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        source = """# Feature

- **FR-001**: Render the dashboard.
- **AC-001**: Given data, when rendering, then the dashboard is visible.
"""
        (spec_dir / "spec.md").write_text(source, encoding="utf-8")
        (spec_dir / "glossary.md").write_text("", encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        (spec_dir / "requirements.lexicon.md").write_text(
            f"""# SOURCE: spec.md
# SOURCE_SHA256: {digest}
ARTIFACT: SPEC
TITLE: Dashboard

REQ: FR-001
GIVEN: data is available
WHEN: the user opens the dashboard
THEN: The system SHALL render the dashboard
OUTPUT: The dashboard is visible
DEPENDS: none
EXAMPLE: AC-001

AC: AC-001
GIVEN: data is available
WHEN: the user opens the dashboard
THEN: The dashboard is visible
""",
            encoding="utf-8",
        )
        state = store.load()
        state["spec_dir"] = str(spec_dir.relative_to(tmp_path))
        store.save(state)

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)

        provider.exec_agent.assert_not_called()
        assert result.verdict == "DONE"
        assert result.state_updates["lexicon_evaluation"] == "passed"
        assert result.state_updates["lexicon_pass"] is True
        assert result.state_updates["lexicon_attempts"] == 0
        assert result.state_updates["lexicon_findings"] == 0
        report_path = Path(result.state_updates["lexicon_report"])
        assert report_path.is_file()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["ok"] is True
        assert report["artifact_sha256"] == hashlib.sha256(
            (spec_dir / "requirements.lexicon.md").read_bytes()
        ).hexdigest()
        assert report["source_sha256"] == hashlib.sha256(
            (spec_dir / "spec.md").read_bytes()
        ).hexdigest()
        assert report["glossary_sha256"] == hashlib.sha256(b"").hexdigest()

    def test_understanding_resume_is_not_blocked_by_downstream_lexicon_gate(
        self,
        tmp_path,
    ):
        ctrl, store = _controller(tmp_path)
        state = store.load()
        state.update({
            "phase": "phase1-understanding",
            "spec_dir": "runs/run-test/specs/001-demo",
        })
        store.save(state)

        guarded = ctrl._guard_spec_lexicon_evidence("phase1-understanding")

        assert guarded == "phase1-understanding"
        assert store.load()["phase"] == "phase1-understanding"

    def test_later_phase_resume_without_current_evidence_reopens_spec_pipeline(
        self, tmp_path
    ):
        ctrl, store = _controller(tmp_path)
        state = store.load()
        state.update({
            "phase": "phase2-decide",
            "iteration": 9,
            "why_fail_count": 2,
            "convergence_forced": True,
            "convergence_detected": True,
            "convergence_guard_fire_count": 3,
            "phase_recommendation": "phase2-decide",
            "spec_dir": "runs/run-test/specs/001-demo",
            "completed_phases": [
                "phase1-what",
                "phase1-lexicon",
                "phase1-understanding",
                "phase1-why2",
                "checkpoint-assess",
            ],
            "phase_dispatch_counts": {
                "phase1-what": 1,
                "phase1-lexicon": 1,
                "phase1-understanding": 1,
                "phase1-why2": 1,
                "checkpoint-assess": 1,
            },
        })
        store.save(state)

        guarded = ctrl._guard_spec_lexicon_evidence("phase2-decide")

        assert guarded == "phase1-lexicon-derive"
        persisted = store.load()
        assert persisted["completed_phases"] == [
            "phase1-what",
            "phase1-understanding",
            "phase1-why2",
        ]
        assert persisted["phase_dispatch_counts"] == {
            "phase1-what": 1,
            "phase1-understanding": 1,
            "phase1-why2": 1,
        }
        assert persisted["iteration"] == 0
        assert persisted["why_fail_count"] == 0
        assert "phase_recommendation" not in persisted
        assert persisted["convergence_forced"] is False
        assert persisted["convergence_detected"] is False
        assert persisted["convergence_guard_fire_count"] == 0

    def test_current_spec_lexicon_evidence_allows_phase1_checkpoint(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        node = ctrl._graph.get("phase1-lexicon")
        store.initialize("r", "greenfield", "msg", 0, node.id)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        source = """# Feature

- **FR-001**: Render the dashboard.
- **AC-001**: Given data, when rendering, then the dashboard is visible.
"""
        (spec_dir / "spec.md").write_text(source, encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        (spec_dir / "requirements.lexicon.md").write_text(
            "# SOURCE: spec.md\n"
            f"# SOURCE_SHA256: {digest}\n"
            "ARTIFACT: SPEC\n"
            "TITLE: Dashboard\n\n"
            "REQ: FR-001\n"
            "GIVEN: data is available\n"
            "WHEN: the user opens the dashboard\n"
            "THEN: The system SHALL render the dashboard\n"
            "OUTPUT: The dashboard is visible\n"
            "DEPENDS: none\n"
            "EXAMPLE: AC-001\n\n"
            "AC: AC-001\n"
            "GIVEN: data is available\n"
            "WHEN: the user opens the dashboard\n"
            "THEN: The dashboard is visible\n",
            encoding="utf-8",
        )
        state = store.load()
        state["spec_dir"] = str(spec_dir.relative_to(tmp_path))
        store.save(state)
        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(node, result, snapshot)
        decision = store.prepare_routing_decision(
            prepared,
            snapshot=snapshot,
            from_phase=node.id,
            to_phase="checkpoint-assess",
        )
        store.advance(
            node.id,
            "checkpoint-assess",
            decision,
        )

        guarded = ctrl._guard_spec_lexicon_evidence("checkpoint-assess")

        assert guarded == "checkpoint-assess"

        (spec_dir / "glossary.md").write_text("**Dashboard**\n", encoding="utf-8")
        guarded = ctrl._guard_spec_lexicon_evidence("checkpoint-assess")

        assert guarded == "phase1-lexicon-derive"

    def test_disabled_spec_lexicon_gate_allows_understanding_without_evidence(
        self, tmp_path
    ):
        _disable_lexicon_gate(tmp_path)
        ctrl, store = _controller(tmp_path)
        state = store.load()
        state["phase"] = "phase1-understanding"
        store.save(state)

        assert (
            ctrl._guard_spec_lexicon_evidence("phase1-understanding")
            == "phase1-understanding"
        )

    @pytest.mark.parametrize(
        "config_text",
        [
            "lexicon_gate:\n  enabled: false\n",
            (
                "lexicon_gate:\n"
                "  enabled: true\n"
                "  artifacts:\n"
                "    spec:\n"
                "      enabled: false\n"
            ),
        ],
        ids=["global-disabled", "spec-subgate-disabled"],
    )
    def test_disabled_spec_lexicon_result_prepares_and_persists_as_pending(
        self,
        tmp_path: Path,
        config_text: str,
    ) -> None:
        config_path = tmp_path / ".echelon" / "config.yml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(config_text, encoding="utf-8")
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "brownfield",
            "msg",
            0,
            "phase1-lexicon",
        )
        stale = store.load()
        stale.update(
            {
                "lexicon_pass": True,
                "lexicon_findings": 0,
                "lexicon_report": "/invented/certificate.json",
            }
        )
        store.save(stale)
        node = ctrl._graph.get("phase1-lexicon")

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(node, result, snapshot)
        next_phase = ctrl._evaluate_transitions(
            node,
            prepared,
            snapshot,
        )

        expected = {
            "lexicon_evaluation": "pending",
            "lexicon_attempts": 0,
        }
        assert result.state_updates == expected
        assert prepared.state_updates == expected
        assert next_phase == "checkpoint-assess"

        decision = store.prepare_routing_decision(
            prepared,
            snapshot=snapshot,
            from_phase=node.id,
            to_phase=next_phase,
        )
        store.advance(
            node.id,
            next_phase,
            decision,
        )
        persisted = store.load()
        assert persisted["lexicon_evaluation"] == "pending"
        assert persisted["lexicon_attempts"] == 0
        assert "lexicon_pass" not in persisted
        assert "lexicon_findings" not in persisted
        assert "lexicon_report" not in persisted
        assert (
            ctrl._guard_spec_lexicon_evidence(next_phase)
            == "checkpoint-assess"
        )

    def test_manual_spec_lexicon_node_is_visible_and_provider_free(
        self, tmp_path, capsys
    ):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "brownfield", "msg", 0, "phase1-lexicon")
        _mark_constitution_complete(tmp_path, store)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        state = store.load()
        state["spec_dir"] = str(spec_dir.relative_to(tmp_path))
        store.save(state)
        ctrl._guard_phase1_quality_evidence = MagicMock(
            side_effect=lambda phase: phase
        )

        result = ctrl.run_single_phase("phase1-lexicon", "validate", "banzai")

        provider.exec_agent.assert_not_called()
        assert result.phase == "phase1-lexicon-derive"
        assert "phase1-lexicon" in store.load()["completed_phases"]
        output = capsys.readouterr().out
        assert "Deterministic Spec Lexicon Gate" in output
        assert "spec Lexicon pending" in output

    def test_gate_config_loads_lexicon_gate_block(self, tmp_path):
        ctrl, _ = _controller(tmp_path)
        cfg = ctrl._lexicon_gate_config()
        assert "lexicon_gate" in cfg
        assert cfg["lexicon_gate"].get("enabled") is True

    @pytest.mark.parametrize(
        ("config_text", "expected"),
        [
            ("lexicon_gate:\n  enabled: false\n", False),
            (
                "lexicon_gate:\n"
                "  enabled: true\n"
                "  artifacts:\n"
                "    spec:\n"
                "      enabled: false\n",
                False,
            ),
            ("lexicon_gate:\n  enabled: true\n", True),
        ],
        ids=["global-disabled", "spec-subgate-disabled", "subgate-default-enabled"],
    )
    def test_gate_config_derives_effective_spec_enablement(
        self,
        tmp_path: Path,
        config_text: str,
        expected: bool,
    ) -> None:
        config_path = tmp_path / ".echelon" / "config.yml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(config_text, encoding="utf-8")
        ctrl, _ = _controller(tmp_path)

        assert ctrl._lexicon_gate_config()["lexicon_gate"]["spec_enabled"] is expected

    def test_spec_quality_gates_use_the_iteration_dispatch_budget(self):
        """WHAT repairs and their verification gates use the repair-cycle budget."""
        from harness.squad import ITERATIVE_PHASES

        assert "phase1-what" in ITERATIVE_PHASES
        assert "phase1-lexicon" in ITERATIVE_PHASES
        assert "phase1-understanding" in ITERATIVE_PHASES

    @pytest.mark.parametrize(
        ("phase_id", "next_phase"),
        [
            ("phase3-tasks-lexicon", "phase3-understanding"),
            ("phase3-consensus-tasks-lexicon", "checkpoint-plan"),
        ],
    )
    def test_run_resumes_tasks_lexicon_nodes_without_provider(
        self,
        tmp_path,
        phase_id,
        next_phase,
    ):
        _disable_lexicon_gate(tmp_path)
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        store.initialize("r", "banzai", "msg", 0, phase_id, max_iterations=3)
        _mark_constitution_complete(tmp_path, store)
        state = store.load()
        state.update({
            "why3_verdict": "PASS",
            "assess2_verdict": "PASS",
            "quality_scores": [{"pass": True, "source": "harness:understanding"}],
        })
        store.save(state)
        ctrl._guard_phase1_quality_evidence = MagicMock(
            side_effect=lambda phase: phase
        )
        ctrl._checkpoint_successful_phase = MagicMock(return_value=False)

        result = ctrl.run_single_phase(
            phase_id,
            "msg",
            "banzai",
        )

        provider.exec_agent.assert_not_called()
        assert result.phase == next_phase
        assert phase_id in store.load()["completed_phases"]
        ctrl._checkpoint_successful_phase.assert_not_called()
        assert store.load()["last_dispatch"][
            "post_dispatch_complete"
        ] is True

    def test_plan_routes_to_visible_tasks_gate_without_hidden_certification(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase3-plan")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "requirements.lexicon.md").write_text(_valid_lexicon_spec(), encoding="utf-8")
        (spec_dir / "tasks.md").write_text("not canonical tasks\n", encoding="utf-8")
        st = store.load()
        st.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
        })
        store.save(st)
        result = self._result({})
        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("guard punted to COMMANDER — not deterministic")):
            nxt = _evaluate_prepared_result(ctrl, node, result)

        assert nxt == "phase3-tasks-lexicon"
        assert result.state_updates == {}
        assert not (spec_dir / "tasks-lexicon-report.json").exists()

    def test_plan_at_iteration_cap_still_routes_to_visible_tasks_gate(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase3-plan")
        state = store.load()
        state.update({"iteration": 3, "max_iterations": 3})
        store.save(state)

        result = self._result({})
        next_phase = _evaluate_prepared_result(ctrl, node, result)

        assert next_phase == "phase3-tasks-lexicon"

    def test_tasks_gate_failure_redispatches_without_provider_or_commander(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        node = ctrl._graph.get("phase3-tasks-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "requirements.lexicon.md").write_text(
            _valid_lexicon_spec(), encoding="utf-8"
        )
        (spec_dir / "tasks.md").write_text("not canonical tasks\n", encoding="utf-8")
        st = store.load()
        st.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
        })
        store.save(st)

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("gate punted to COMMANDER")):
            nxt = _evaluate_prepared_result(ctrl, node, result)

        provider.exec_agent.assert_not_called()
        assert nxt == "phase3-plan"
        assert result.state_updates["tasks_lexicon_action"] == "repair"
        assert result.state_updates["tasks_lexicon_pass"] is False
        assert result.state_updates["tasks_lexicon_attempts"] == 1
        report_path = Path(result.state_updates["tasks_lexicon_report"])
        assert report_path.is_file()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["ok"] is False
        assert any(item["code"] == "parse-error" for item in report["findings"])

    def test_tasks_gate_exhaustion_prepares_one_controller_owned_block(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase3-tasks-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "requirements.lexicon.md").write_text(
            _valid_lexicon_spec(), encoding="utf-8"
        )
        (spec_dir / "tasks.md").write_text("not canonical tasks\n", encoding="utf-8")
        state = store.load()
        state.update({
            "phase": node.id,
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "tasks_lexicon_attempts": 2,
        })
        store.save(state)

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(node, result, snapshot)

        assert prepared.state_updates["tasks_lexicon_action"] == "block"
        assert (
            prepared.control_updates["blocked_reason"]
            == "tasks_lexicon_gate_exhausted"
        )
        assert prepared.control_updates["tasks_lexicon_gate_exhausted"] is True
        assert "lexicon_gate_exhausted" not in prepared.control_updates
        assert ctrl._evaluate_transitions(node, prepared, snapshot) == "terminal-blocked"

    def test_tasks_gate_exhaustion_persists_report_backed_terminal_state(
        self,
        tmp_path,
        monkeypatch,
    ):
        """The public controller path must retain evidence needed by PLAN repair."""
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase3-tasks-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "requirements.lexicon.md").write_text(
            _valid_lexicon_spec(), encoding="utf-8"
        )
        (spec_dir / "tasks.md").write_text("not canonical tasks\n", encoding="utf-8")
        state = store.load()
        state.update(
            {
                "phase": node.id,
                "iteration": 0,
                "max_iterations": 3,
                "spec_dir": str(spec_dir.relative_to(tmp_path)),
                "tasks_lexicon_attempts": 2,
            }
        )
        store.save(state)
        monkeypatch.setattr(
            ctrl, "_guard_constitution_provenance", lambda phase: phase
        )
        monkeypatch.setattr(
            ctrl, "_guard_spec_lexicon_evidence", lambda phase: phase
        )
        monkeypatch.setattr(
            ctrl, "_guard_phase1_quality_evidence", lambda phase: phase
        )
        monkeypatch.setattr(
            ctrl, "_guard_understanding_evidence", lambda phase: phase
        )

        result = ctrl.run_single_phase(node.id, "validate tasks", "banzai")

        persisted = store.load()
        assert result.status == "blocked"
        assert result.phase == "terminal-blocked"
        assert persisted["blocked_reason"] == "tasks_lexicon_gate_exhausted"
        assert persisted["tasks_lexicon_gate_exhausted"] is True
        assert persisted["tasks_lexicon_action"] == "block"
        assert persisted["tasks_lexicon_pass"] is False
        assert persisted["tasks_lexicon_attempts"] == 3
        assert persisted["tasks_lexicon_findings"] > 0
        report_path = Path(persisted["tasks_lexicon_report"])
        assert report_path.is_file()
        assert json.loads(report_path.read_text(encoding="utf-8"))["ok"] is False

    def test_tasks_gate_pass_falls_through_to_understanding(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        node = ctrl._graph.get("phase3-tasks-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        _write_valid_plan_artifacts(spec_dir)
        st = store.load()
        st.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "tasks_lexicon_pass": False,
            "tasks_lexicon_attempts": 3,
        })
        store.save(st)
        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        with patch.object(ctrl, "_judgment_dispatch",
                          side_effect=AssertionError("gate punted to COMMANDER")):
            nxt = _evaluate_prepared_result(ctrl, node, result)

        provider.exec_agent.assert_not_called()
        assert nxt == "phase3-understanding"
        assert result.state_updates["tasks_lexicon_action"] == "proceed"
        assert result.state_updates["tasks_lexicon_pass"] is True
        assert result.state_updates["tasks_lexicon_attempts"] == 0

    def test_tasks_gate_materializes_run_targets_before_validation(
        self,
        tmp_path,
    ):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        node = ctrl._graph.get("phase3-tasks-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        _write_valid_plan_artifacts(spec_dir)
        (spec_dir / "targets.yml").unlink()
        (spec_dir / "spec.md").write_text("# Dashboard\n", encoding="utf-8")
        _mark_constitution_complete(tmp_path, store)
        state = store.load()
        state.update({
            "phase": node.id,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "implementation_targets": ["sources/app"],
            "quality_scores": [{"pass": True, "source": "harness:understanding"}],
        })
        store.save(state)
        ctrl._guard_spec_lexicon_evidence = MagicMock(side_effect=lambda phase: phase)
        ctrl._guard_phase1_quality_evidence = MagicMock(side_effect=lambda phase: phase)

        result = ctrl.run_single_phase(node.id, "validate", "banzai")

        provider.exec_agent.assert_not_called()
        assert result.phase == "phase3-understanding"
        assert (spec_dir / "targets.yml").is_file()

    def test_consensus_revalidates_tasks_after_plan2(self, tmp_path):
        provider = _mock_provider()
        ctrl, store = _controller(tmp_path, provider=provider)
        consensus = ctrl._graph.get("phase3-consensus")
        node = ctrl._graph.get("phase3-consensus-tasks-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        _write_valid_plan_artifacts(spec_dir)
        (spec_dir / "tasks.md").write_text("PLAN2 broke the task grammar\n", encoding="utf-8")
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "why3-verdict": "PASS",
            "assess2-verdict": "PASS",
            "tasks_lexicon_pass": True,
        })
        store.save(state)

        consensus_result = self._result({})
        assert (
            _evaluate_prepared_result(ctrl, consensus, consensus_result)
            == "phase3-consensus-tasks-lexicon"
        )
        assert consensus_result.state_updates == {}

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        with patch.object(
            ctrl,
            "_judgment_dispatch",
            side_effect=AssertionError("post-PLAN2 tasks gate punted to COMMANDER"),
        ):
            nxt = _evaluate_prepared_result(ctrl, node, result)

        provider.exec_agent.assert_not_called()
        assert nxt == "phase3-plan"
        assert result.state_updates["tasks_lexicon_pass"] is False

    def test_tasks_gate_rejects_invalid_target_ownership(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase3-tasks-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        _write_valid_plan_artifacts(spec_dir)
        (spec_dir / "tasks.md").write_text(
            _valid_tasks().replace("target=sources/app", "target=sources/other"),
            encoding="utf-8",
        )
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
        })
        store.save(state)

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        assert _evaluate_prepared_result(ctrl, node, result) == "phase3-plan"
        report = json.loads(
            Path(result.state_updates["tasks_lexicon_report"]).read_text(encoding="utf-8")
        )
        assert any(item["code"] == "undeclared-target" for item in report["findings"])

    def test_tasks_gate_reports_missing_plan_outputs(self, tmp_path):
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase3-consensus-tasks-lexicon")
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        _write_valid_plan_artifacts(spec_dir)
        (spec_dir / "risk-matrix.md").unlink()
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "why3-verdict": "PASS",
            "assess2-verdict": "PASS",
        })
        store.save(state)

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        assert _evaluate_prepared_result(ctrl, node, result) == "phase3-plan"
        report = json.loads(
            Path(result.state_updates["tasks_lexicon_report"]).read_text(encoding="utf-8")
        )
        assert {
            item["artifact"]
            for item in report["findings"]
            if item["code"] == "missing-plan-output"
        } == {"risk-matrix.md"}

    def test_what_routes_to_visible_spec_gate_without_commander(self, tmp_path):
        """WHAT cannot bypass the visible deterministic spec Lexicon node."""
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-what")
        st = store.load()
        st["iteration"] = 0
        st["max_iterations"] = 3
        st["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(st)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")

        with patch.object(
            ctrl,
            "_judgment_dispatch",
            side_effect=AssertionError("missing Lexicon result punted to COMMANDER"),
        ):
            nxt = _evaluate_prepared_result(
                ctrl,
                node,
                self._result(
                    {"evidence_resolution_status": "not_required"},
                    verdict="DONE",
                ),
            )

        assert nxt == "phase1-understanding"

    def test_spec_gate_marks_missing_derived_artifact_pending_without_false_result(self, tmp_path):
        """No derived artifact means validation has not happened, not failed."""
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon")
        store.initialize("r", "greenfield", "msg", 0, node.id)
        st = store.load()
        st["iteration"] = 0
        st["max_iterations"] = 3
        st["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(st)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
        stale_report = spec_dir / "spec-lexicon-report.json"
        stale_report.write_text('{"ok": false}\n', encoding="utf-8")
        state = store.load()
        state["lexicon_report"] = str(stale_report)
        state["lexicon_findings"] = 4
        store.save(state)
        result = ctrl._executors["deterministic_lexicon"].execute(node, store)

        with patch.object(
            ctrl,
            "_judgment_dispatch",
            side_effect=AssertionError("missing artifact punted to COMMANDER"),
        ):
            snapshot = store.capture_routing_snapshot(
                expected_phase=node.id
            )
            prepared = ctrl._prepare_phase_result(
                node,
                result,
                snapshot,
            )
            nxt = ctrl._evaluate_transitions(node, prepared, snapshot)

        assert nxt == "phase1-lexicon-derive"
        assert "lexicon_pass" not in result.state_updates
        assert "lexicon_findings" not in result.state_updates
        assert "lexicon_report" not in result.state_updates
        assert result.state_updates["lexicon_evaluation"] == "pending"

        decision = store.prepare_routing_decision(
            prepared,
            snapshot=snapshot,
            from_phase=node.id,
            to_phase=nxt,
        )
        store.advance(
            node.id,
            nxt,
            decision,
        )
        persisted = store.load()
        assert persisted["lexicon_evaluation"] == "pending"
        assert "lexicon_pass" not in persisted
        assert "lexicon_findings" not in persisted
        assert "lexicon_report" not in persisted

    def test_spec_gate_uses_controller_validation_not_agent_stale_failure(self, tmp_path):
        """A valid artifact advances even if the agent reports stale failed state."""
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon")
        store.initialize("r", "greenfield", "msg", 0, node.id)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        source = """# Feature\n\n- **FR-001**: Render the dashboard.\n- **AC-001**: Given data, when rendering, then the dashboard is visible.\n"""
        (spec_dir / "spec.md").write_text(source, encoding="utf-8")
        (spec_dir / "glossary.md").write_text("", encoding="utf-8")
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        (spec_dir / "requirements.lexicon.md").write_text(
            f"""# SOURCE: spec.md
# SOURCE_SHA256: {digest}
ARTIFACT: SPEC
TITLE: Dashboard

REQ: FR-001
GIVEN: data is available
WHEN: the user opens the dashboard
THEN: The system SHALL render the dashboard
OUTPUT: The dashboard is visible
DEPENDS: none
EXAMPLE: AC-001

AC: AC-001
GIVEN: data is available
WHEN: the user opens the dashboard
THEN: The dashboard is visible
""",
            encoding="utf-8",
        )
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 10,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "lexicon_pass": False,
            "lexicon_attempts": 3,
            "lexicon_findings": 55,
        })
        store.save(state)
        result = ctrl._executors["deterministic_lexicon"].execute(node, store)

        nxt = _evaluate_prepared_result(ctrl, node, result)

        assert nxt == "checkpoint-assess"
        assert result.state_updates["lexicon_evaluation"] == "passed"
        assert result.state_updates["lexicon_pass"] is True
        assert result.state_updates["lexicon_attempts"] == 0
        assert result.state_updates["lexicon_findings"] == 0
        report_path = Path(result.state_updates["lexicon_report"])
        assert report_path.is_file()
        assert json.loads(report_path.read_text(encoding="utf-8"))["ok"] is True

    def test_spec_gate_records_false_only_after_controller_validation(self, tmp_path):
        """An invalid derived artifact receives a real, controller-certified failure."""
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon")
        store.initialize("r", "greenfield", "msg", 0, node.id)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Feature\n", encoding="utf-8")
        (spec_dir / "requirements.lexicon.md").write_text("not Lexicon grammar\n", encoding="utf-8")
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
            "lexicon_attempts": 1,
        })
        store.save(state)
        result = ctrl._executors["deterministic_lexicon"].execute(node, store)

        assert (
            _evaluate_prepared_result(ctrl, node, result)
            == "phase1-lexicon-derive"
        )
        assert result.state_updates["lexicon_evaluation"] == "failed"
        assert result.state_updates["lexicon_pass"] is False
        assert result.state_updates["lexicon_findings"] > 0
        assert result.state_updates["lexicon_attempts"] == 2
        report_path = Path(result.state_updates["lexicon_report"])
        assert report_path.is_file()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["schema_version"] == 1
        assert report["artifact_type"] == "SPEC"
        assert report["artifact_path"] == str(spec_dir / "requirements.lexicon.md")
        assert report["source_path"] == str(spec_dir / "spec.md")
        assert report["glossary_path"] == str(spec_dir / "glossary.md")
        assert report["ok"] is False
        assert report["findings"]
        assert {"code", "message"}.issubset(report["findings"][0])

    def test_lexicon_derivation_without_artifact_progress_blocks(self, tmp_path):
        """A failed Lexicon repair pass must change the derived artifact."""
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon-derive")
        store.initialize("r", "greenfield", "msg", 0, node.id)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Feature\n", encoding="utf-8")
        derived = spec_dir / "requirements.lexicon.md"
        derived.write_text("not Lexicon grammar\n", encoding="utf-8")
        artifact_sha = hashlib.sha256(derived.read_bytes()).hexdigest()
        report = spec_dir / "spec-lexicon-report.json"
        report.write_text(
            json.dumps(
                {
                    "ok": False,
                    "artifact_path": str(derived),
                    "artifact_sha256": artifact_sha,
                    "findings": [
                        {
                            "code": "parse-error",
                            "message": "not canonical grammar",
                            "line": 1,
                            "span": "not",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        state = store.load()
        state.update(
            {
                "spec_dir": str(spec_dir.relative_to(tmp_path)),
                "lexicon_evaluation": "failed",
                "lexicon_pass": False,
                "lexicon_attempts": 1,
                "lexicon_findings": 1,
                "lexicon_report": str(report),
            }
        )
        store.save(state)
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "output_files": [
                    str(derived),
                ],
                "state_updates": {},
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )

        next_phase = _coordinate_prepared_result(ctrl, node, result)

        assert next_phase == "terminal-blocked"
        blocked = store.load()
        assert blocked["status"] == "blocked"
        assert blocked["blocked_reason"] == "lexicon_repair_no_artifact_progress"
        assert blocked["lexicon_repair_no_artifact_progress"] is True

    def test_spec_gate_uses_resolved_local_paths_in_report(self, tmp_path):
        config_dir = tmp_path / ".echelon"
        config_dir.mkdir(parents=True)
        (config_dir / "config.yml").write_text(
            "lexicon_gate:\n"
            "  enabled: true\n"
            "  artifacts:\n"
            "    spec:\n"
            "      enabled: true\n",
            encoding="utf-8",
        )
        (config_dir / "local.yml").write_text(
            "lexicon_gate:\n"
            "  glossary_file: domain-glossary.md\n"
            "  artifacts:\n"
            "    spec:\n"
            "      path: controlled-requirements.md\n"
            "      source_ref: product-spec.md\n",
            encoding="utf-8",
        )
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon")
        spec_dir = tmp_path / "runs/run-test/specs/001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "product-spec.md").write_text("# Product spec\n", encoding="utf-8")
        (spec_dir / "controlled-requirements.md").write_text(
            "not Lexicon grammar\n", encoding="utf-8"
        )
        (spec_dir / "domain-glossary.md").write_text("", encoding="utf-8")
        state = store.load()
        state.update({
            "iteration": 0,
            "max_iterations": 3,
            "spec_dir": str(spec_dir.relative_to(tmp_path)),
        })
        store.save(state)
        result = ctrl._executors["deterministic_lexicon"].execute(node, store)

        assert (
            _evaluate_prepared_result(ctrl, node, result)
            == "phase1-lexicon-derive"
        )
        report = json.loads(
            Path(result.state_updates["lexicon_report"]).read_text(encoding="utf-8")
        )
        assert report["artifact_path"] == str(spec_dir / "controlled-requirements.md")
        assert report["source_path"] == str(spec_dir / "product-spec.md")
        assert report["glossary_path"] == str(spec_dir / "domain-glossary.md")

    def test_spec_gate_blocks_on_exhaustion_when_configured_hard(self, tmp_path):
        """A hard Lexicon gate cannot fall through after its final repair pass."""
        (tmp_path / ".echelon").mkdir()
        (tmp_path / ".echelon" / "config.yml").write_text(
            "lexicon_gate:\n"
            "  enabled: true\n"
            "  on_exhausted: block\n"
            "  artifacts:\n"
            "    spec:\n"
            "      enabled: true\n"
            "      path: requirements.lexicon.md\n",
            encoding="utf-8",
        )
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon")
        store.initialize("r", "greenfield", "msg", 0, node.id)
        st = store.load()
        st["iteration"] = 3
        st["max_iterations"] = 3
        st["spec_dir"] = "runs/run-test/specs/001-demo"
        store.save(st)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(node, result, snapshot)
        before_routing = store.load()
        decision = ctrl._coordinate_transition_routing(
            node,
            prepared,
            snapshot,
        )

        assert type(decision).__name__ == "PreparedRoutingDecision"
        assert decision.to_phase == "terminal-blocked"
        assert store.load() == before_routing
        store.advance(node.id, decision.to_phase, decision)
        state = store.load()
        assert state["status"] == "blocked"
        assert state["blocked_reason"] == "lexicon_gate_exhausted"

    def test_pending_spec_gate_cannot_warn_past_iteration_cap(self, tmp_path):
        """Phase 1 Lexicon certification remains hard even under warn config."""
        (tmp_path / ".echelon").mkdir()
        (tmp_path / ".echelon" / "config.yml").write_text(
            "lexicon_gate:\n"
            "  enabled: true\n"
            "  on_exhausted: warn\n"
            "  artifacts:\n"
            "    spec:\n"
            "      enabled: true\n"
            "      path: requirements.lexicon.md\n",
            encoding="utf-8",
        )
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon")
        store.initialize("r", "greenfield", "msg", 0, node.id)
        state = store.load()
        state.update({
            "iteration": 3,
            "max_iterations": 3,
            "spec_dir": "runs/run-test/specs/001-demo",
        })
        store.save(state)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
        result = ctrl._executors["deterministic_lexicon"].execute(node, store)

        snapshot = store.capture_routing_snapshot(expected_phase=node.id)
        prepared = ctrl._prepare_phase_result(node, result, snapshot)
        decision = ctrl._coordinate_transition_routing(
            node,
            prepared,
            snapshot,
        )

        assert decision.to_phase == "terminal-blocked"
        assert result.state_updates["lexicon_evaluation"] == "pending"
        assert "lexicon_pass" not in result.state_updates
        assert "lexicon_warning_waiver" not in prepared.state_updates
        assert "lexicon_warning_waiver" not in result.state_updates

    def test_spec_gate_does_not_trust_stale_failure_without_validation(self, tmp_path):
        """Stale failure state cannot exhaust a gate whose artifact was not validated."""
        (tmp_path / ".echelon").mkdir()
        (tmp_path / ".echelon" / "config.yml").write_text(
            "lexicon_gate:\n"
            "  enabled: true\n"
            "  max_repair_attempts: 3\n"
            "  on_exhausted: block\n"
            "  artifacts:\n"
            "    spec:\n"
            "      enabled: true\n"
            "      path: requirements.lexicon.md\n",
            encoding="utf-8",
        )
        ctrl, store = _controller(tmp_path)
        node = ctrl._graph.get("phase1-lexicon")
        st = store.load()
        st["iteration"] = 0
        st["max_iterations"] = 10
        st["spec_dir"] = "runs/run-test/specs/001-demo"
        st["lexicon_pass"] = False
        st["lexicon_attempts"] = 3
        store.save(st)
        spec_dir = tmp_path / "runs" / "run-test" / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")

        result = ctrl._executors["deterministic_lexicon"].execute(node, store)
        nxt = _evaluate_prepared_result(ctrl, node, result)

        assert nxt == "phase1-lexicon-derive"
        assert result.state_updates["lexicon_evaluation"] == "pending"
        assert "lexicon_pass" not in result.state_updates
        assert result.state_updates["lexicon_attempts"] == 0


class TestControllerCompletionOrchestration:
    class _MiningProbe:
        drawer_id = f"drawer_{'0' * 64}"

        def __init__(self) -> None:
            self.mine_calls = 0
            self.write_count = 0
            self.verify_calls = 0
            self.verify_ok = True

        def plan_canonical_bytes(self, *_args, **_kwargs):
            return [self.drawer_id]

        def mine_canonical_bytes(self, *_args, **_kwargs):
            self.mine_calls += 1
            if self.write_count:
                return SimpleNamespace(
                    total=1,
                    written=0,
                    already_present=1,
                    unavailable=0,
                    failed=0,
                    drawer_ids=[self.drawer_id],
                    expected_drawer_ids=[self.drawer_id],
                )
            self.write_count += 1
            return SimpleNamespace(
                total=1,
                written=1,
                already_present=0,
                unavailable=0,
                failed=0,
                drawer_ids=[self.drawer_id],
                expected_drawer_ids=[self.drawer_id],
            )

        def verify_canonical_bytes(self, *_args, **_kwargs):
            self.verify_calls += 1
            return self.verify_ok and self.write_count == 1

    def test_fresh_completion_authority_requires_durable_state(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        prepared = _install_empty_routed_completion(ctrl, store)
        state_path = ctrl._squad_dir / "state.json"
        before = state_path.read_bytes()
        stage = prepared._transaction_root
        confirm = MagicMock(
            side_effect=StateDurabilityError(
                "injected confirmation failure",
                stage="confirm",
            )
        )
        monkeypatch.setattr(
            store,
            "confirm_durable_state",
            confirm,
        )

        first = ctrl._drain_pending_controller_completion()
        second = ctrl._drain_pending_controller_completion()

        assert first.recovered is False
        assert second.recovered is False
        assert confirm.call_count == 2
        assert state_path.read_bytes() == before
        assert stage.is_dir()

    def test_fresh_publication_authority_requires_durable_state(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        prepared, targets = _sealed_publication_fixture(ctrl)
        _install_publication_marker(store, prepared)
        state_path = ctrl._squad_dir / "state.json"
        before = state_path.read_bytes()
        stage = (
            ctrl._squad_dir
            / ".publication-outbox"
            / prepared.marker.transaction_id
        )
        confirm = MagicMock(
            side_effect=StateDurabilityError(
                "injected confirmation failure",
                stage="confirm",
            )
        )
        monkeypatch.setattr(
            store,
            "confirm_durable_state",
            confirm,
        )

        assert ctrl._recover_pending_external_publication() is False
        assert ctrl._recover_pending_external_publication() is False

        assert confirm.call_count == 2
        assert state_path.read_bytes() == before
        assert stage.is_dir()
        assert targets["replace"].read_text(encoding="utf-8") == (
            "old replace\n"
        )
        assert not targets["create"].exists()
        assert targets["delete"].read_text(encoding="utf-8") == (
            "old delete\n"
        )

    def test_publication_final_clear_retains_stage_when_confirmation_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        prepared, targets = _sealed_publication_fixture(ctrl)
        marker = _install_publication_marker(store, prepared)
        transaction_root = (
            ctrl._squad_dir
            / ".publication-outbox"
            / prepared.marker.transaction_id
        )
        monkeypatch.setattr(
            store,
            "confirm_durable_state",
            MagicMock(
                side_effect=StateDurabilityError(
                    "injected clear confirmation failure",
                    stage="confirm",
                )
            ),
        )

        assert ctrl._publish_and_finalize(prepared, marker) is False

        cleared = store.load()
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in cleared
        assert "external_publication_failure" not in cleared
        assert transaction_root.is_dir()
        assert targets["replace"].read_text(encoding="utf-8") == (
            "new replace\n"
        )
        assert targets["create"].read_text(encoding="utf-8") == (
            "new create\n"
        )
        assert not targets["delete"].exists()

    def test_final_clear_retains_stage_without_durable_confirmation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        prepared = _install_empty_routed_completion(ctrl, store)
        store.complete_controller_completion(prepared)
        cleared = store.load()
        assert PENDING_CONTROLLER_COMPLETION_KEY not in cleared
        assert prepared._transaction_root.is_dir()
        monkeypatch.setattr(
            store,
            "confirm_durable_state",
            MagicMock(
                side_effect=StateDurabilityError(
                    "injected confirmation failure",
                    stage="confirm",
                )
            ),
        )

        ctrl._discard_completed_controller_stage(prepared)

        assert prepared._transaction_root.is_dir()

    def test_orphan_cleanup_requires_durable_state(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        orphan = prepare_controller_completion(
            tmp_path,
            ctrl._squad_dir,
            completion_id=uuid.uuid4().hex,
            origin="routed",
            publication={"kind": "none"},
            route={
                "kind": "routed",
                "from_phase": "phase1-what",
                "to_phase": "phase1-why1",
                "manual_phase_run": False,
                "record_completion": True,
            },
            effect_plan=(),
            checkpoint_prestate={"kind": "none"},
            context_reason="power-loss old-state orphan",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        )
        before = (ctrl._squad_dir / "state.json").read_bytes()
        monkeypatch.setattr(
            store,
            "confirm_durable_state",
            MagicMock(
                side_effect=StateDurabilityError(
                    "injected confirmation failure",
                    stage="confirm",
                )
            ),
        )

        assert ctrl._cleanup_controller_completion_orphans() is False
        assert (ctrl._squad_dir / "state.json").read_bytes() == before
        assert orphan._transaction_root.is_dir()

    def test_power_loss_old_state_has_no_effect_and_safe_orphan(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        orphan = prepare_controller_completion(
            tmp_path,
            ctrl._squad_dir,
            completion_id=uuid.uuid4().hex,
            origin="routed",
            publication={"kind": "none"},
            route={
                "kind": "routed",
                "from_phase": "phase1-what",
                "to_phase": "phase1-why1",
                "manual_phase_run": False,
                "record_completion": True,
            },
            effect_plan=(),
            checkpoint_prestate={"kind": "none"},
            context_reason="old state survives marker replacement",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        )
        effect = MagicMock(
            side_effect=AssertionError(
                "old state without marker authorized an effect"
            )
        )
        monkeypatch.setattr(
            ctrl,
            "_apply_controller_completion_effect",
            effect,
        )

        outcome = ctrl._drain_pending_controller_completion()

        assert outcome.recovered is False
        effect.assert_not_called()
        assert orphan._transaction_root.is_dir()
        assert ctrl._cleanup_controller_completion_orphans() is True
        assert not orphan._transaction_root.exists()

    def test_power_loss_new_state_keeps_stage_and_recovers(
        self,
        tmp_path: Path,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        prepared = _install_empty_routed_completion(ctrl, store)
        assert prepared._transaction_root.is_dir()
        assert PENDING_CONTROLLER_COMPLETION_KEY in store.load()
        del ctrl
        fresh, fresh_store = _controller(tmp_path)

        outcome = fresh._drain_pending_controller_completion()

        assert outcome.recovered is True
        assert PENDING_CONTROLLER_COMPLETION_KEY not in fresh_store.load()
        assert not prepared._transaction_root.exists()

    @pytest.mark.parametrize("with_publication", [False, True])
    def test_fresh_controller_starts_from_exact_route_cas(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        with_publication: bool,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        publication = None
        targets: dict[str, Path] = {}
        if with_publication:
            publication, targets = _sealed_publication_fixture(ctrl)
        prepared = prepare_controller_completion(
            tmp_path,
            ctrl._squad_dir,
            completion_id=uuid.uuid4().hex,
            origin="routed",
            publication=(
                {
                    "kind": "external",
                    "marker": publication.marker.to_dict(),
                }
                if publication is not None
                else {"kind": "none"}
            ),
            route={
                "kind": "routed",
                "from_phase": "phase1-what",
                "to_phase": "phase1-why1",
                "manual_phase_run": False,
                "record_completion": True,
            },
            effect_plan=(),
            checkpoint_prestate={"kind": "none"},
            context_reason="fresh route CAS matrix",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        )
        _install_prepared_routed_completion(
            store,
            prepared,
            token_usage_delta=23,
        )
        committed = store.load()
        assert committed["token_usage"] == 23
        assert committed[PENDING_CONTROLLER_COMPLETION_KEY][
            "completion_id"
        ] == prepared.marker.completion_id
        assert (
            PENDING_EXTERNAL_PUBLICATION_KEY in committed
        ) is with_publication

        del ctrl
        fresh, fresh_store = _controller(tmp_path)
        runner = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                SquadResult.from_state(fresh_store.load())
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", runner)

        fresh.run("msg", "banzai")

        completed = fresh_store.load()
        assert runner.call_count == 1
        assert completed["token_usage"] == 23
        assert PENDING_CONTROLLER_COMPLETION_KEY not in completed
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in completed
        assert completed["last_dispatch"]["dispatch_id"] == (
            prepared.marker.completion_id
        )
        assert completed["last_dispatch"][
            "post_dispatch_complete"
        ] is True
        if with_publication:
            assert targets["replace"].read_text(encoding="utf-8") == (
                "new replace\n"
            )
            assert targets["create"].read_text(encoding="utf-8") == (
                "new create\n"
            )
            assert not targets["delete"].exists()

    @pytest.mark.parametrize(
        ("effect", "boundary"),
        [
            (effect, boundary)
            for effect in (
                "journal",
                "timing",
                "checkpoint",
                "context",
                "mining",
            )
            for boundary in ("before_receipt", "before_step_cas")
        ],
    )
    def test_fresh_controller_recovers_every_effect_boundary_once(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        effect: str,
        boundary: str,
    ) -> None:
        ctrl, store, prepared = _install_single_effect_completion(
            tmp_path,
            effect,
        )
        completion_id = prepared.marker.completion_id
        crashed = False
        context_generations = 0
        miner = self._MiningProbe()

        if effect == "context":
            prepare_context = (
                completion_module.prepare_or_load_completion_context
            )

            def generate_context(
                _project_root,
                _squad_dir,
                *,
                user_request,
                drawers,
                output_dir,
            ):
                nonlocal context_generations
                context_generations += 1
                output_dir.mkdir(parents=True, exist_ok=True)
                for name in completion_module._CONTEXT_OUTPUT_NAMES:
                    (output_dir / name).write_text(
                        f"{name}|{user_request}|{tuple(drawers)}\n",
                        encoding="utf-8",
                    )
                return SimpleNamespace(context_dir=output_dir)

            def context_wrapper(current, **kwargs):
                def fault(stage: str) -> None:
                    nonlocal crashed
                    if (
                        boundary == "before_receipt"
                        and stage == "after_generation"
                        and not crashed
                    ):
                        crashed = True
                        raise KeyboardInterrupt(
                            "crash before context receipt"
                        )

                return prepare_context(
                    current,
                    **kwargs,
                    generator=generate_context,
                    fault_hook=fault,
                )

            monkeypatch.setattr(
                squad_module,
                "prepare_or_load_completion_context",
                context_wrapper,
            )

        if effect == "mining":
            apply_mining = (
                completion_module.apply_or_verify_completion_mining
            )
            monkeypatch.setattr(
                completion_module,
                "_completion_local_mining_plan",
                lambda **_kwargs: (miner.drawer_id,),
            )

            def mining_wrapper(current, **kwargs):
                def fault(stage: str) -> None:
                    nonlocal crashed
                    if (
                        boundary == "before_receipt"
                        and stage == "after_mining"
                        and not crashed
                    ):
                        crashed = True
                        raise KeyboardInterrupt(
                            "crash before mining receipt"
                        )

                return apply_mining(
                    current,
                    **kwargs,
                    miner_factory=lambda: miner,
                    fault_hook=fault,
                )

            monkeypatch.setattr(
                squad_module,
                "apply_or_verify_completion_mining",
                mining_wrapper,
            )

        if (
            boundary == "before_receipt"
            and effect in {"journal", "timing", "checkpoint"}
        ):
            persist = squad_module.persist_completion_effect_receipt

            def crash_before_receipt(current, current_effect, receipt):
                nonlocal crashed
                if current_effect == effect and not crashed:
                    crashed = True
                    raise KeyboardInterrupt(
                        f"crash before {effect} receipt"
                    )
                return persist(current, current_effect, receipt)

            monkeypatch.setattr(
                squad_module,
                "persist_completion_effect_receipt",
                crash_before_receipt,
            )

        if boundary == "before_step_cas":
            advance_step = store.advance_controller_completion

            def crash_before_step(current):
                nonlocal crashed
                if current.marker.step == effect and not crashed:
                    crashed = True
                    raise KeyboardInterrupt(
                        f"crash before {effect} step CAS"
                    )
                return advance_step(current)

            monkeypatch.setattr(
                store,
                "advance_controller_completion",
                crash_before_step,
            )

        before_runner = MagicMock(
            side_effect=AssertionError(
                "phase runner executed before completion recovery"
            )
        )
        monkeypatch.setattr(ctrl, "_run_locked", before_runner)
        with pytest.raises(KeyboardInterrupt):
            ctrl.run("msg", "banzai")
        assert crashed is True
        assert before_runner.call_count == 0
        interrupted = store.load()
        assert interrupted[PENDING_CONTROLLER_COMPLETION_KEY][
            "completion_id"
        ] == completion_id

        del ctrl
        fresh, fresh_store = _controller(tmp_path)
        after_runner = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                SquadResult.from_state(fresh_store.load())
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", after_runner)

        fresh.run("msg", "banzai")

        completed = fresh_store.load()
        assert after_runner.call_count == 1
        assert PENDING_CONTROLLER_COMPLETION_KEY not in completed
        assert "controller_completion_failure" not in completed
        if effect == "mining":
            terminal = completed["last_terminal_completion"]
            assert terminal["completion_id"] == completion_id
            assert len(terminal["phase_a_active_source_sha256"]) == 64
            assert (
                len(
                    terminal[
                        "phase_a_published_postimage_sha256"
                    ]
                )
                == 64
            )
            assert miner.write_count == 1
            assert miner.mine_calls == (
                2 if boundary == "before_receipt" else 1
            )
        else:
            assert completed["token_usage"] == 17
            dispatch = completed["last_dispatch"]
            assert dispatch["dispatch_id"] == completion_id
            assert dispatch["post_dispatch_complete"] is True

        if effect == "journal":
            rows = [
                json.loads(line)
                for line in (
                    fresh._squad_dir / "reasoning-journal.jsonl"
                ).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            owned = [
                row
                for row in rows
                if row.get("controller_completion", {}).get(
                    "completion_id"
                )
                == completion_id
            ]
            assert len(owned) == 1
        elif effect == "timing":
            events, diagnostics = (
                fresh._telemetry_store.read_phase_timings()
            )
            owned = [
                event
                for event in events
                if event.completion_id == completion_id
            ]
            assert diagnostics == ()
            assert len(owned) == 2
            assert len({event.effect_id for event in owned}) == 2
        elif effect == "checkpoint":
            messages = subprocess.run(
                ["git", "log", "--format=%B"],
                cwd=tmp_path,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            assert messages.count(completion_id) == 1
            ledger = json.loads(
                (
                    fresh._squad_dir
                    / "specs"
                    / "001-demo"
                    / ".echelon"
                    / "checkpoints.json"
                ).read_text(encoding="utf-8")
            )
            assert [
                row["completion_id"]
                for row in ledger["checkpoints"]
            ].count(completion_id) == 1
        elif effect == "context":
            visible = fresh._squad_dir / "context"
            assert {
                path.name for path in visible.iterdir()
            } == set(completion_module._CONTEXT_OUTPUT_NAMES)
            assert context_generations == (
                2 if boundary == "before_receipt" else 1
            )

    @pytest.mark.parametrize(
        "effect",
        ["journal", "timing", "checkpoint", "context", "mining"],
    )
    def test_fresh_controller_recovers_each_effect_step_saved_then_raised(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        effect: str,
    ) -> None:
        ctrl, store, prepared = _install_single_effect_completion(
            tmp_path,
            effect,
        )
        completion_id = prepared.marker.completion_id
        context_generations = 0
        miner = self._MiningProbe()

        if effect == "context":
            prepare_context = (
                completion_module.prepare_or_load_completion_context
            )

            def generate_context(
                _project_root,
                _squad_dir,
                *,
                user_request,
                drawers,
                output_dir,
            ):
                nonlocal context_generations
                context_generations += 1
                output_dir.mkdir(parents=True, exist_ok=True)
                for name in completion_module._CONTEXT_OUTPUT_NAMES:
                    (output_dir / name).write_text(
                        f"{name}|{user_request}|{tuple(drawers)}\n",
                        encoding="utf-8",
                    )
                return SimpleNamespace(context_dir=output_dir)

            def context_wrapper(current, **kwargs):
                return prepare_context(
                    current,
                    **kwargs,
                    generator=generate_context,
                )

            monkeypatch.setattr(
                squad_module,
                "prepare_or_load_completion_context",
                context_wrapper,
            )

        if effect == "mining":
            apply_mining = (
                completion_module.apply_or_verify_completion_mining
            )
            monkeypatch.setattr(
                completion_module,
                "_completion_local_mining_plan",
                lambda **_kwargs: (miner.drawer_id,),
            )

            def mining_wrapper(current, **kwargs):
                return apply_mining(
                    current,
                    **kwargs,
                    miner_factory=lambda: miner,
                )

            monkeypatch.setattr(
                squad_module,
                "apply_or_verify_completion_mining",
                mining_wrapper,
            )

        original_save = store._save_unlocked
        injected = False

        def save_step_then_crash(candidate):
            nonlocal injected
            pending = candidate.get(
                PENDING_CONTROLLER_COMPLETION_KEY
            )
            if (
                not injected
                and isinstance(pending, dict)
                and pending.get("completion_id") == completion_id
                and pending.get("step") == "complete"
            ):
                injected = True
                original_save(candidate)
                raise KeyboardInterrupt(
                    f"crash after {effect} step save"
                )
            return original_save(candidate)

        monkeypatch.setattr(
            store,
            "_save_unlocked",
            save_step_then_crash,
        )
        runner_before = MagicMock(
            side_effect=AssertionError(
                "phase work ran before effect-step recovery"
            )
        )
        monkeypatch.setattr(ctrl, "_run_locked", runner_before)

        with pytest.raises(KeyboardInterrupt):
            ctrl.run("msg", "banzai")

        assert injected is True
        assert runner_before.call_count == 0
        assert store.load()[PENDING_CONTROLLER_COMPLETION_KEY][
            "step"
        ] == "complete"
        del ctrl

        fresh, fresh_store = _controller(tmp_path)
        runner_after = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                SquadResult.from_state(fresh_store.load())
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", runner_after)

        fresh.run("msg", "banzai")

        completed = fresh_store.load()
        assert runner_after.call_count == 1
        assert PENDING_CONTROLLER_COMPLETION_KEY not in completed
        assert "controller_completion_failure" not in completed
        if effect == "mining":
            assert completed["last_terminal_completion"][
                "completion_id"
            ] == completion_id
            assert miner.mine_calls == 1
            assert miner.write_count == 1
        else:
            assert completed["token_usage"] == 17
            assert completed["last_dispatch"]["dispatch_id"] == (
                completion_id
            )
            assert completed["last_dispatch"][
                "post_dispatch_complete"
            ] is True

        if effect == "journal":
            rows = [
                json.loads(line)
                for line in (
                    fresh._squad_dir / "reasoning-journal.jsonl"
                ).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            assert sum(
                row.get("controller_completion", {}).get(
                    "completion_id"
                )
                == completion_id
                for row in rows
            ) == 1
        elif effect == "timing":
            events, diagnostics = (
                fresh._telemetry_store.read_phase_timings()
            )
            owned = [
                event
                for event in events
                if event.completion_id == completion_id
            ]
            assert diagnostics == ()
            assert len(owned) == 2
            assert len({event.effect_id for event in owned}) == 2
        elif effect == "checkpoint":
            messages = subprocess.run(
                ["git", "log", "--format=%B"],
                cwd=tmp_path,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            assert messages.count(completion_id) == 1
            ledger = json.loads(
                (
                    fresh._squad_dir
                    / "specs"
                    / "001-demo"
                    / ".echelon"
                    / "checkpoints.json"
                ).read_text(encoding="utf-8")
            )
            assert [
                row["completion_id"]
                for row in ledger["checkpoints"]
            ].count(completion_id) == 1
        elif effect == "context":
            visible = fresh._squad_dir / "context"
            assert {
                path.name for path in visible.iterdir()
            } == set(completion_module._CONTEXT_OUTPUT_NAMES)
            assert context_generations == 1

    @pytest.mark.parametrize(
        "transition",
        ["handoff", "advance", "record_failure", "complete"],
    )
    @pytest.mark.parametrize("save_then_raise", [False, True])
    def test_fresh_controller_recovers_each_completion_state_save_boundary(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        transition: str,
        save_then_raise: bool,
    ) -> None:
        publication_targets: dict[str, Path] = {}
        if transition == "handoff":
            ctrl, store = _controller(tmp_path)
            store.initialize(
                "r",
                "greenfield",
                "msg",
                0,
                "phase1-what",
            )
            publication, publication_targets = (
                _sealed_publication_fixture(ctrl)
            )
            prepared = prepare_controller_completion(
                tmp_path,
                ctrl._squad_dir,
                completion_id=uuid.uuid4().hex,
                origin="routed",
                publication={
                    "kind": "external",
                    "marker": publication.marker.to_dict(),
                },
                route={
                    "kind": "routed",
                    "from_phase": "phase1-what",
                    "to_phase": "phase1-why1",
                    "manual_phase_run": False,
                    "record_completion": True,
                },
                effect_plan=(),
                checkpoint_prestate={"kind": "none"},
                context_reason="state save boundary handoff",
                mine_phase_a=False,
                judgment_payload_sha256=(),
                judgments=(),
            )
            _install_prepared_routed_completion(
                store,
                prepared,
                token_usage_delta=17,
            )
        else:
            ctrl, store, prepared = (
                _install_single_effect_completion(
                    tmp_path,
                    "journal",
                )
            )

        completion_id = prepared.marker.completion_id
        transaction_root = prepared._transaction_root
        if transition == "complete":
            current_raw = store.load()[
                PENDING_CONTROLLER_COMPLETION_KEY
            ]
            ctrl._apply_controller_completion_effect(
                prepared,
                store.load(),
            )
            one_ahead = load_prepared_controller_completion(
                tmp_path,
                ctrl._squad_dir,
                current_raw,
            )
            store.advance_controller_completion(one_ahead)
        elif transition == "record_failure":
            monkeypatch.setattr(
                ctrl,
                "_apply_controller_completion_effect",
                MagicMock(
                    side_effect=CompletionError("stage_io")
                ),
            )

        original_save = store._save_unlocked
        injected = False

        def is_target_save(candidate: dict[str, object]) -> bool:
            pending = candidate.get(
                PENDING_CONTROLLER_COMPLETION_KEY
            )
            if transition == "handoff":
                return (
                    PENDING_EXTERNAL_PUBLICATION_KEY
                    not in candidate
                    and isinstance(pending, dict)
                    and pending.get("step") == "complete"
                )
            if transition == "advance":
                return (
                    isinstance(pending, dict)
                    and pending.get("step") == "complete"
                )
            if transition == "record_failure":
                failure = candidate.get(
                    "controller_completion_failure"
                )
                return (
                    isinstance(failure, dict)
                    and failure.get("code") == "stage_io"
                )
            dispatch = candidate.get("last_dispatch")
            return (
                PENDING_CONTROLLER_COMPLETION_KEY not in candidate
                and isinstance(dispatch, dict)
                and dispatch.get("post_dispatch_complete") is True
            )

        def crash_at_target_save(candidate):
            nonlocal injected
            if not injected and is_target_save(candidate):
                injected = True
                if save_then_raise:
                    original_save(candidate)
                raise KeyboardInterrupt(
                    f"crash at {transition} state save"
                )
            return original_save(candidate)

        monkeypatch.setattr(
            store,
            "_save_unlocked",
            crash_at_target_save,
        )
        before_runner = MagicMock(
            side_effect=AssertionError(
                "phase work ran before state recovery"
            )
        )
        monkeypatch.setattr(ctrl, "_run_locked", before_runner)

        with pytest.raises(KeyboardInterrupt):
            ctrl.run("msg", "banzai")

        assert injected is True
        assert before_runner.call_count == 0
        del ctrl

        fresh, fresh_store = _controller(tmp_path)
        after_runner = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                SquadResult.from_state(fresh_store.load())
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", after_runner)

        fresh.run("msg", "banzai")

        completed = fresh_store.load()
        assert after_runner.call_count == 1
        assert PENDING_CONTROLLER_COMPLETION_KEY not in completed
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in completed
        assert "controller_completion_failure" not in completed
        assert completed["token_usage"] == 17
        assert completed["last_dispatch"]["dispatch_id"] == (
            completion_id
        )
        assert completed["last_dispatch"][
            "post_dispatch_complete"
        ] is True
        assert not transaction_root.exists()

        if transition == "handoff":
            assert publication_targets["replace"].read_text(
                encoding="utf-8"
            ) == "new replace\n"
            assert publication_targets["create"].read_text(
                encoding="utf-8"
            ) == "new create\n"
            assert not publication_targets["delete"].exists()
        else:
            rows = [
                json.loads(line)
                for line in (
                    fresh._squad_dir / "reasoning-journal.jsonl"
                ).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            assert sum(
                row.get("controller_completion", {}).get(
                    "completion_id"
                )
                == completion_id
                for row in rows
            ) == 1

    @pytest.mark.parametrize("with_publication", [False, True])
    @pytest.mark.parametrize("save_then_raise", [False, True])
    def test_fresh_controller_resolves_route_cas_save_boundary(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        save_then_raise: bool,
        with_publication: bool,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        _configure_tasks_lexicon_route(
            ctrl,
            store,
            monkeypatch,
        )
        publication_targets: dict[str, Path] = {}
        publication_root: Path | None = None
        if with_publication:
            publication, publication_targets = (
                _sealed_publication_fixture(ctrl)
            )
            publication_root = publication._transaction_root
            monkeypatch.setattr(
                ctrl,
                "_prepare_external_phase_effects",
                lambda *_args, **_kwargs: publication,
            )
        original_save = store._save_unlocked
        injected = False

        def crash_at_route_save(candidate):
            nonlocal injected
            pending = candidate.get(
                PENDING_CONTROLLER_COMPLETION_KEY
            )
            dispatch = candidate.get("last_dispatch")
            if (
                not injected
                and isinstance(pending, dict)
                and isinstance(dispatch, dict)
                and dispatch.get("post_dispatch_complete") is False
            ):
                injected = True
                if save_then_raise:
                    original_save(candidate)
                raise KeyboardInterrupt("crash at route CAS save")
            return original_save(candidate)

        monkeypatch.setattr(
            store,
            "_save_unlocked",
            crash_at_route_save,
        )

        with pytest.raises(KeyboardInterrupt):
            ctrl.run_single_phase(
                "phase3-tasks-lexicon",
                "msg",
                "banzai",
            )

        assert injected is True
        outbox = ctrl._squad_dir / ".completion-outbox"
        staged = [
            path
            for path in outbox.iterdir()
            if path.is_dir()
        ]
        assert len(staged) == 1
        completion_id = staged[0].name
        interrupted = store.load()
        assert (
            PENDING_CONTROLLER_COMPLETION_KEY in interrupted
        ) is save_then_raise
        assert (
            PENDING_EXTERNAL_PUBLICATION_KEY in interrupted
        ) is (save_then_raise and with_publication)
        del ctrl

        fresh, fresh_store = _controller(tmp_path)
        runner = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                SquadResult.from_state(fresh_store.load())
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", runner)

        fresh.run("msg", "banzai")

        completed = fresh_store.load()
        assert runner.call_count == 1
        assert PENDING_CONTROLLER_COMPLETION_KEY not in completed
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in completed
        assert completed["token_usage"] == 0
        assert not staged[0].exists()
        if publication_root is not None:
            assert not publication_root.exists()
        if save_then_raise:
            assert completed["last_dispatch"]["dispatch_id"] == (
                completion_id
            )
            assert completed["last_dispatch"][
                "post_dispatch_complete"
            ] is True
            if with_publication:
                assert publication_targets["replace"].read_text(
                    encoding="utf-8"
                ) == "new replace\n"
                assert publication_targets["create"].read_text(
                    encoding="utf-8"
                ) == "new create\n"
                assert not publication_targets["delete"].exists()
        else:
            assert completed["phase"] == "phase3-tasks-lexicon"
            assert completed.get("last_dispatch") is None
            if with_publication:
                assert publication_targets["replace"].read_text(
                    encoding="utf-8"
                ) == "old replace\n"
                assert not publication_targets["create"].exists()
                assert publication_targets["delete"].read_text(
                    encoding="utf-8"
                ) == "old delete\n"

    @pytest.mark.parametrize("with_publication", [False, True])
    @pytest.mark.parametrize("save_then_raise", [False, True])
    def test_fresh_controller_resolves_terminal_begin_save_boundary(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        save_then_raise: bool,
        with_publication: bool,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "DONE",
        )
        active = ctrl._squad_dir / "specs" / "001-demo"
        published = tmp_path / "specs" / "001-demo"
        active.mkdir(parents=True)
        published.mkdir(parents=True)
        spec_bytes = b"# Terminal state-save boundary\n"
        (active / "spec.md").write_bytes(spec_bytes)
        (published / "spec.md").write_bytes(spec_bytes)
        state = store.load()
        state.update(
            {
                "status": "done",
                "spec_id": "001-demo",
                "spec_dir": str(active.relative_to(tmp_path)),
                "published_spec_dir": str(
                    published.relative_to(tmp_path)
                ),
            }
        )
        store.save(state)
        publication = None
        publication_targets: dict[str, Path] = {}
        publication_root: Path | None = None
        if with_publication:
            publication, publication_targets = (
                _sealed_publication_fixture(ctrl)
            )
            publication_root = publication._transaction_root
        prepared = prepare_controller_completion(
            tmp_path,
            ctrl._squad_dir,
            completion_id=uuid.uuid4().hex,
            origin="terminal",
            publication=(
                {
                    "kind": "external",
                    "marker": publication.marker.to_dict(),
                }
                if publication is not None
                else {"kind": "none"}
            ),
            route={
                "kind": "terminal",
                "terminal_phase": "DONE",
            },
            effect_plan=(),
            checkpoint_prestate={"kind": "none"},
            context_reason="terminal state save boundary",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase="DONE",
        )
        original_save = store._save_unlocked
        injected = False

        def crash_at_terminal_begin(candidate):
            nonlocal injected
            pending = candidate.get(
                PENDING_CONTROLLER_COMPLETION_KEY
            )
            if not injected and isinstance(pending, dict):
                injected = True
                if save_then_raise:
                    original_save(candidate)
                raise KeyboardInterrupt(
                    "crash at terminal completion begin"
                )
            return original_save(candidate)

        monkeypatch.setattr(
            store,
            "_save_unlocked",
            crash_at_terminal_begin,
        )

        with pytest.raises(KeyboardInterrupt):
            store.begin_terminal_controller_completion(
                prepared,
                snapshot=snapshot,
            )

        assert injected is True
        assert (
            PENDING_CONTROLLER_COMPLETION_KEY in store.load()
        ) is save_then_raise
        assert (
            PENDING_EXTERNAL_PUBLICATION_KEY in store.load()
        ) is (save_then_raise and with_publication)
        transaction_root = prepared._transaction_root
        del ctrl

        fresh, fresh_store = _controller(tmp_path)
        runner = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                SquadResult.from_state(fresh_store.load())
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", runner)

        fresh.run("msg", "banzai")

        completed = fresh_store.load()
        assert runner.call_count == 1
        assert PENDING_CONTROLLER_COMPLETION_KEY not in completed
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in completed
        assert not transaction_root.exists()
        if publication_root is not None:
            assert not publication_root.exists()
        if save_then_raise:
            terminal = completed["last_terminal_completion"]
            assert terminal["completion_id"] == (
                prepared.marker.completion_id
            )
            assert len(
                terminal["phase_a_active_source_sha256"]
            ) == 64
            assert len(
                terminal[
                    "phase_a_published_postimage_sha256"
                ]
            ) == 64
            if with_publication:
                assert publication_targets["replace"].read_text(
                    encoding="utf-8"
                ) == "new replace\n"
                assert publication_targets["create"].read_text(
                    encoding="utf-8"
                ) == "new create\n"
                assert not publication_targets["delete"].exists()
        else:
            assert "last_terminal_completion" not in completed
            if with_publication:
                assert publication_targets["replace"].read_text(
                    encoding="utf-8"
                ) == "old replace\n"
                assert not publication_targets["create"].exists()
                assert publication_targets["delete"].read_text(
                    encoding="utf-8"
                ) == "old delete\n"

    @pytest.mark.parametrize("drift", ["spec", "drawer"])
    def test_fresh_mining_recovery_rejects_bound_postimage_drift(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        drift: str,
    ) -> None:
        ctrl, store, prepared = _install_single_effect_completion(
            tmp_path,
            "mining",
        )
        miner = self._MiningProbe()
        apply_mining = (
            completion_module.apply_or_verify_completion_mining
        )
        monkeypatch.setattr(
            completion_module,
            "_completion_local_mining_plan",
            lambda **_kwargs: (miner.drawer_id,),
        )

        def mining_wrapper(current, **kwargs):
            return apply_mining(
                current,
                **kwargs,
                miner_factory=lambda: miner,
            )

        monkeypatch.setattr(
            squad_module,
            "apply_or_verify_completion_mining",
            mining_wrapper,
        )
        advance_step = store.advance_controller_completion
        crashed = False

        def crash_before_step(current):
            nonlocal crashed
            if current.marker.step == "mining" and not crashed:
                crashed = True
                raise KeyboardInterrupt(
                    "crash before mining step CAS"
                )
            return advance_step(current)

        monkeypatch.setattr(
            store,
            "advance_controller_completion",
            crash_before_step,
        )
        with pytest.raises(KeyboardInterrupt):
            ctrl.run("msg", "banzai")
        assert crashed is True
        assert miner.mine_calls == 1
        assert miner.write_count == 1

        if drift == "spec":
            state = store.load()
            published = tmp_path / str(state["published_spec_dir"])
            (published / "spec.md").write_text(
                "# Drifted canonical specification\n",
                encoding="utf-8",
            )
        else:
            miner.verify_ok = False

        del ctrl
        fresh, fresh_store = _controller(tmp_path)
        runner = MagicMock(
            side_effect=AssertionError(
                "drifted mining receipt reached phase work"
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", runner)

        fresh.run("msg", "banzai")

        failed = fresh_store.load()
        assert runner.call_count == 0
        assert failed[PENDING_CONTROLLER_COMPLETION_KEY][
            "completion_id"
        ] == prepared.marker.completion_id
        assert failed["controller_completion_failure"]["code"] == (
            "receipts_mismatch"
        )
        assert miner.mine_calls == 1
        assert miner.write_count == 1

    @pytest.mark.parametrize(
        "timing_boundary",
        ["after_close", "after_open"],
    )
    def test_fresh_controller_adopts_each_tagged_timing_boundary(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        timing_boundary: str,
    ) -> None:
        ctrl, store, prepared = _install_single_effect_completion(
            tmp_path,
            "timing",
        )
        completion_id = prepared.marker.completion_id
        apply_timing = (
            completion_module.apply_or_verify_completion_timing
        )
        crashed = False

        def timing_wrapper(intent, telemetry, **kwargs):
            def fault(stage: str) -> None:
                nonlocal crashed
                if stage == timing_boundary and not crashed:
                    crashed = True
                    raise KeyboardInterrupt(
                        f"crash at timing {timing_boundary}"
                    )

            return apply_timing(
                intent,
                telemetry,
                **kwargs,
                fault_hook=fault,
            )

        monkeypatch.setattr(
            squad_module,
            "apply_or_verify_completion_timing",
            timing_wrapper,
        )
        with pytest.raises(KeyboardInterrupt):
            ctrl.run("msg", "banzai")
        assert crashed is True

        del ctrl
        fresh, fresh_store = _controller(tmp_path)
        runner = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                SquadResult.from_state(fresh_store.load())
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", runner)

        fresh.run("msg", "banzai")

        assert runner.call_count == 1
        events, diagnostics = fresh._telemetry_store.read_phase_timings()
        owned = [
            event
            for event in events
            if event.completion_id == completion_id
        ]
        assert diagnostics == ()
        assert len(owned) == 2
        assert len({event.effect_id for event in owned}) == 2
        assert fresh_store.load()["token_usage"] == 17

    @pytest.mark.parametrize(
        "checkpoint_boundary",
        ["after_commit", "after_ledger"],
    )
    def test_fresh_controller_adopts_each_checkpoint_boundary(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        checkpoint_boundary: str,
    ) -> None:
        ctrl, store, prepared = _install_single_effect_completion(
            tmp_path,
            "checkpoint",
        )
        completion_id = prepared.marker.completion_id
        apply_checkpoint = (
            completion_module.create_or_recover_completion_checkpoint
        )
        crashed = False

        def checkpoint_wrapper(intent, **kwargs):
            def fault(stage: str) -> None:
                nonlocal crashed
                if stage == checkpoint_boundary and not crashed:
                    crashed = True
                    raise KeyboardInterrupt(
                        f"crash at checkpoint {checkpoint_boundary}"
                    )

            return apply_checkpoint(
                intent,
                **kwargs,
                fault_hook=fault,
            )

        monkeypatch.setattr(
            squad_module,
            "create_or_recover_completion_checkpoint",
            checkpoint_wrapper,
        )
        with pytest.raises(KeyboardInterrupt):
            ctrl.run("msg", "banzai")
        assert crashed is True

        del ctrl
        fresh, fresh_store = _controller(tmp_path)
        runner = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                SquadResult.from_state(fresh_store.load())
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", runner)

        fresh.run("msg", "banzai")

        assert runner.call_count == 1
        messages = subprocess.run(
            ["git", "log", "--format=%B"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert messages.count(completion_id) == 1
        ledger = json.loads(
            (
                fresh._squad_dir
                / "specs"
                / "001-demo"
                / ".echelon"
                / "checkpoints.json"
            ).read_text(encoding="utf-8")
        )
        assert [
            row["completion_id"]
            for row in ledger["checkpoints"]
        ].count(completion_id) == 1
        assert fresh_store.load()["token_usage"] == 17

    @pytest.mark.parametrize(
        "context_name",
        list(completion_module._CONTEXT_OUTPUT_NAMES),
    )
    def test_fresh_controller_recovers_each_context_install_boundary(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        context_name: str,
    ) -> None:
        ctrl, store, _ = _install_single_effect_completion(
            tmp_path,
            "context",
        )
        prepare_context = (
            completion_module.prepare_or_load_completion_context
        )
        install_context = (
            completion_module.install_or_verify_completion_context
        )
        generations = 0
        crashed = False

        def generate(
            _project_root,
            _squad_dir,
            *,
            user_request,
            drawers,
            output_dir,
        ):
            nonlocal generations
            generations += 1
            output_dir.mkdir(parents=True, exist_ok=True)
            for name in completion_module._CONTEXT_OUTPUT_NAMES:
                (output_dir / name).write_text(
                    f"{name}|{user_request}|{tuple(drawers)}\n",
                    encoding="utf-8",
                )
            return SimpleNamespace(context_dir=output_dir)

        def prepare_wrapper(current, **kwargs):
            return prepare_context(
                current,
                **kwargs,
                generator=generate,
            )

        def install_wrapper(current, **kwargs):
            def fault(stage: str) -> None:
                nonlocal crashed
                if (
                    stage == f"after_install:{context_name}"
                    and not crashed
                ):
                    crashed = True
                    raise KeyboardInterrupt(
                        f"crash after context install {context_name}"
                    )

            return install_context(
                current,
                **kwargs,
                fault_hook=fault,
            )

        monkeypatch.setattr(
            squad_module,
            "prepare_or_load_completion_context",
            prepare_wrapper,
        )
        monkeypatch.setattr(
            squad_module,
            "install_or_verify_completion_context",
            install_wrapper,
        )
        with pytest.raises(KeyboardInterrupt):
            ctrl.run("msg", "banzai")
        assert crashed is True

        del ctrl
        fresh, fresh_store = _controller(tmp_path)
        runner = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                SquadResult.from_state(fresh_store.load())
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", runner)

        fresh.run("msg", "banzai")

        assert runner.call_count == 1
        visible = fresh._squad_dir / "context"
        assert {
            path.name for path in visible.iterdir()
        } == set(completion_module._CONTEXT_OUTPUT_NAMES)
        assert generations == 1
        assert fresh_store.load()["token_usage"] == 17

    @pytest.mark.parametrize("entrypoint", ["normal", "manual"])
    def test_completion_recovery_precedes_entrypoint_logic(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        entrypoint: str,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        prepared = _install_empty_routed_completion(ctrl, store)
        calls: list[str] = []
        del ctrl
        fresh, fresh_store = _controller(tmp_path)

        def after_recovery(*_args, **_kwargs):
            recovered = fresh_store.load()
            assert PENDING_CONTROLLER_COMPLETION_KEY not in recovered
            assert recovered["last_dispatch"][
                "post_dispatch_complete"
            ] is True
            calls.append(entrypoint)
            return SquadResult.from_state(recovered)

        if entrypoint == "normal":
            monkeypatch.setattr(fresh, "_run_locked", after_recovery)
            fresh.run("msg", "banzai")
        else:
            monkeypatch.setattr(
                fresh,
                "_run_single_phase_locked",
                after_recovery,
            )
            fresh.run_single_phase(
                prepared.intent.route["to_phase"],
                "msg",
                "banzai",
            )

        assert calls == [entrypoint]

    def test_recovered_manual_completion_stops_without_redispatch(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        _install_empty_routed_completion(
            ctrl,
            store,
            manual_phase_run=True,
        )
        del ctrl
        fresh, fresh_store = _controller(tmp_path)
        callback = MagicMock(
            side_effect=AssertionError(
                "manual recovery redispatched the completed phase"
            )
        )
        monkeypatch.setattr(
            fresh,
            "_run_single_phase_locked",
            callback,
        )

        result = fresh.run_single_phase(
            "phase1-why1",
            "msg",
            "banzai",
        )

        assert callback.call_count == 0
        assert result.phase == "phase1-why1"
        assert (
            PENDING_CONTROLLER_COMPLETION_KEY
            not in fresh_store.load()
        )

    def test_routing_seals_completion_and_publication_in_one_decision(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        _configure_tasks_lexicon_route(
            ctrl,
            store,
            monkeypatch,
        )
        publication, _ = _sealed_publication_fixture(ctrl)
        node = ctrl._graph.get("phase3-tasks-lexicon")
        result = ctrl._executors["deterministic_lexicon"].execute(
            node,
            store,
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase=node.id
        )
        prepared_result = ctrl._prepare_phase_result(
            node,
            result,
            snapshot,
        )

        decision = ctrl._coordinate_transition_routing(
            node,
            prepared_result,
            snapshot,
            additional_state_updates={
                PENDING_EXTERNAL_PUBLICATION_KEY: (
                    publication.marker.to_dict()
                ),
            },
            manual_phase_run=True,
        )

        updates = dict(decision.transaction_state_updates)
        marker = updates[PENDING_CONTROLLER_COMPLETION_KEY]
        assert updates[PENDING_EXTERNAL_PUBLICATION_KEY] == (
            publication.marker.to_dict()
        )
        assert decision.dispatch_id == marker["completion_id"]
        assert marker["step"] == "awaiting_publication"
        loaded = load_prepared_controller_completion(
            tmp_path,
            ctrl._squad_dir,
            marker,
        )
        assert loaded.intent.route == {
            "kind": "routed",
            "from_phase": node.id,
            "to_phase": decision.to_phase,
            "manual_phase_run": True,
            "record_completion": True,
        }
        assert loaded.intent.publication == {
            "kind": "external",
            "marker": publication.marker.to_dict(),
        }

    def test_fresh_controller_resumes_completion_after_publication_handoff(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        _configure_tasks_lexicon_route(
            ctrl,
            store,
            monkeypatch,
        )
        publication, _ = _sealed_publication_fixture(ctrl)
        monkeypatch.setattr(
            ctrl,
            "_prepare_external_phase_effects",
            lambda *_args, **_kwargs: publication,
        )
        handoff = store.handoff_external_publication

        def crash_after_handoff(marker, completion):
            handoff(marker, completion)
            raise KeyboardInterrupt("simulated post-handoff crash")

        monkeypatch.setattr(
            store,
            "handoff_external_publication",
            crash_after_handoff,
        )

        with pytest.raises(KeyboardInterrupt):
            ctrl.run_single_phase(
                "phase3-tasks-lexicon",
                "msg",
                "banzai",
            )

        handed = store.load()
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in handed
        assert handed[PENDING_CONTROLLER_COMPLETION_KEY]["step"] != (
            "awaiting_publication"
        )

        fresh, _ = _controller(tmp_path)
        runner = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                SquadResult.from_state(store.load())
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", runner)

        fresh.run("msg", "banzai")

        assert runner.call_count == 1
        recovered = store.load()
        assert PENDING_CONTROLLER_COMPLETION_KEY not in recovered
        assert "controller_completion_failure" not in recovered
        assert recovered["last_dispatch"][
            "post_dispatch_complete"
        ] is True

    def test_fresh_controller_after_final_clear_does_not_repeat_effect(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store, prepared = _install_single_effect_completion(
            tmp_path,
            "journal",
        )
        completion_id = prepared.marker.completion_id
        transaction_root = prepared._transaction_root
        complete = store.complete_controller_completion

        def crash_after_clear(current, **kwargs):
            complete(current, **kwargs)
            raise KeyboardInterrupt("crash after final clear")

        monkeypatch.setattr(
            store,
            "complete_controller_completion",
            crash_after_clear,
        )
        with pytest.raises(KeyboardInterrupt):
            ctrl.run("msg", "banzai")

        cleared = store.load()
        assert PENDING_CONTROLLER_COMPLETION_KEY not in cleared
        assert cleared["last_dispatch"][
            "post_dispatch_complete"
        ] is True
        assert transaction_root.exists()

        del ctrl
        fresh, fresh_store = _controller(tmp_path)
        runner = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                SquadResult.from_state(fresh_store.load())
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", runner)

        fresh.run("msg", "banzai")

        assert runner.call_count == 1
        assert not transaction_root.exists()
        rows = [
            json.loads(line)
            for line in (
                fresh._squad_dir / "reasoning-journal.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert sum(
            row.get("controller_completion", {}).get(
                "completion_id"
            )
            == completion_id
            for row in rows
        ) == 1
        assert fresh_store.load()["token_usage"] == 17

    @pytest.mark.parametrize("save_then_raise", [False, True])
    @pytest.mark.parametrize("variant", ["terminal", "phase4"])
    def test_fresh_controller_after_terminal_or_phase4_final_clear(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        variant: str,
        save_then_raise: bool,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        from_phase = (
            "DONE" if variant == "terminal" else "phase4-document"
        )
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            from_phase,
        )
        active = ctrl._squad_dir / "specs" / "001-demo"
        published = tmp_path / "specs" / "001-demo"
        active.mkdir(parents=True)
        published.mkdir(parents=True)
        spec_bytes = (
            b"# Durable terminal provenance\n\n"
            b"- FR-001: Recovery SHALL remain exact.\n"
        )
        (active / "spec.md").write_bytes(spec_bytes)
        (published / "spec.md").write_bytes(spec_bytes)
        for name in REQUIRED_PHASE_A_BUILD_INPUTS:
            if name == "spec.md":
                continue
            content = (
                "# Durable constitution\n\n"
                "- Recovery effects are replay-safe.\n"
                if name == "constitution.md"
                else (
                    '{\n'
                    '  "status": "pass",\n'
                    '  "findings": [],\n'
                    '  "sources": ["spec.md", "requirements-overview.md", "plan.md", "tasks.md"]\n'
                    '}\n'
                    if name == "plan-conformance.json"
                    else f"# Durable {name}\n\nFR-001\n"
                )
            )
            (active / name).write_text(content, encoding="utf-8")
            (published / name).write_text(content, encoding="utf-8")
        state = store.load()
        state.update(
            {
                "status": (
                    "done"
                    if variant == "terminal"
                    else "running"
                ),
                "spec_id": "001-demo",
                "spec_dir": str(active.relative_to(tmp_path)),
                "published_spec_dir": str(
                    published.relative_to(tmp_path)
                ),
            }
        )
        store.save(state)
        completion_id = uuid.uuid4().hex
        prepared = prepare_controller_completion(
            tmp_path,
            ctrl._squad_dir,
            completion_id=completion_id,
            origin=(
                "terminal"
                if variant == "terminal"
                else "routed"
            ),
            publication={"kind": "none"},
            route=(
                {
                    "kind": "terminal",
                    "terminal_phase": "DONE",
                }
                if variant == "terminal"
                else {
                    "kind": "routed",
                    "from_phase": "phase4-document",
                    "to_phase": "DONE",
                    "manual_phase_run": False,
                    "record_completion": True,
                }
            ),
            effect_plan=(),
            checkpoint_prestate={"kind": "none"},
            context_reason=f"{variant} final clear",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        )
        if variant == "terminal":
            snapshot = store.capture_routing_snapshot(
                expected_phase="DONE",
            )
            store.begin_terminal_controller_completion(
                prepared,
                snapshot=snapshot,
            )
        else:
            _install_prepared_routed_completion(
                store,
                prepared,
                token_usage_delta=17,
            )

        transaction_root = prepared._transaction_root
        complete = store.complete_controller_completion

        def crash_at_clear(current, **kwargs):
            if save_then_raise:
                complete(current, **kwargs)
            raise KeyboardInterrupt(
                f"crash at {variant} final clear"
            )

        monkeypatch.setattr(
            store,
            "complete_controller_completion",
            crash_at_clear,
        )
        with pytest.raises(KeyboardInterrupt):
            ctrl.run("msg", "banzai")

        interrupted = store.load()
        assert (
            PENDING_CONTROLLER_COMPLETION_KEY in interrupted
        ) is (not save_then_raise)
        assert transaction_root.exists()
        if save_then_raise:
            if variant == "terminal":
                provenance = interrupted[
                    "last_terminal_completion"
                ]
                assert provenance["completion_id"] == completion_id
                assert len(
                    provenance["phase_a_active_source_sha256"]
                ) == 64
                assert len(
                    provenance[
                        "phase_a_published_postimage_sha256"
                    ]
                ) == 64
            else:
                assert interrupted["last_dispatch"][
                    "dispatch_id"
                ] == completion_id
                assert interrupted["last_dispatch"][
                    "post_dispatch_complete"
                ] is True
                assert len(
                    interrupted["phase_a_active_source_sha256"]
                ) == 64
                assert len(
                    interrupted[
                        "phase_a_published_postimage_sha256"
                    ]
                ) == 64
        elif variant == "terminal":
            assert "last_terminal_completion" not in interrupted
        else:
            assert interrupted["last_dispatch"][
                "post_dispatch_complete"
            ] is False
            assert "phase_a_active_source_sha256" not in interrupted
            assert (
                "phase_a_published_postimage_sha256"
                not in interrupted
            )
        del ctrl

        fresh, fresh_store = _controller(tmp_path)
        runner = None
        restage = None
        if variant == "phase4":
            restage = MagicMock(
                side_effect=AssertionError(
                    "durable Phase 4 inventory was restaged"
                )
            )
            monkeypatch.setattr(
                fresh,
                "_prepare_external_phase_effects",
                restage,
            )
            monkeypatch.setattr(
                fresh,
                "_guard_spec_lexicon_evidence",
                lambda phase: phase,
            )
            monkeypatch.setattr(
                fresh,
                "_guard_understanding_evidence",
                lambda phase: phase,
            )
            monkeypatch.setattr(
                fresh,
                "_apply_phase_recommendation_guard",
                lambda phase: phase,
            )
            monkeypatch.setattr(
                fresh,
                "_guard_constitution_provenance",
                lambda phase: phase,
            )
            monkeypatch.setattr(
                fresh,
                "_ensure_telemetry_manifest",
                lambda: None,
            )
            result = fresh.run("msg", "banzai")
            assert result.status == "done"
            assert restage.call_count == 0
        else:
            runner = MagicMock(
                side_effect=lambda *_args, **_kwargs: (
                    SquadResult.from_state(fresh_store.load())
                )
            )
            monkeypatch.setattr(fresh, "_run_locked", runner)
            fresh.run("msg", "banzai")

        recovered = fresh_store.load()
        if runner is not None:
            assert runner.call_count == 1
        assert PENDING_CONTROLLER_COMPLETION_KEY not in recovered
        assert not transaction_root.exists()
        if variant == "terminal":
            provenance = recovered["last_terminal_completion"]
            assert provenance["completion_id"] == completion_id
            assert len(
                provenance["phase_a_active_source_sha256"]
            ) == 64
            assert len(
                provenance[
                    "phase_a_published_postimage_sha256"
                ]
            ) == 64
            if save_then_raise:
                assert provenance == interrupted[
                    "last_terminal_completion"
                ]
        else:
            assert recovered["last_dispatch"]["dispatch_id"] == (
                completion_id
            )
            assert recovered["last_dispatch"][
                "post_dispatch_complete"
            ] is True
            assert len(
                recovered["phase_a_active_source_sha256"]
            ) == 64
            assert len(
                recovered[
                    "phase_a_published_postimage_sha256"
                ]
            ) == 64
            if save_then_raise:
                assert recovered["last_dispatch"] == (
                    interrupted["last_dispatch"]
                )
            assert recovered["token_usage"] == 17

    @pytest.mark.parametrize("save_then_raise", [False, True])
    def test_fresh_controller_after_manual_origin_final_clear(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        save_then_raise: bool,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        prepared = _install_empty_routed_completion(
            ctrl,
            store,
            manual_phase_run=True,
        )
        completion_id = prepared.marker.completion_id
        transaction_root = prepared._transaction_root
        complete = store.complete_controller_completion

        def crash_at_clear(current, **kwargs):
            if save_then_raise:
                complete(current, **kwargs)
            raise KeyboardInterrupt(
                "crash at manual-origin final clear"
            )

        monkeypatch.setattr(
            store,
            "complete_controller_completion",
            crash_at_clear,
        )
        runner_before = MagicMock(
            side_effect=AssertionError(
                "manual-origin phase work ran before recovery"
            )
        )
        monkeypatch.setattr(ctrl, "_run_locked", runner_before)

        with pytest.raises(KeyboardInterrupt):
            ctrl.run("msg", "banzai")

        assert runner_before.call_count == 0
        interrupted = store.load()
        assert (
            PENDING_CONTROLLER_COMPLETION_KEY in interrupted
        ) is (not save_then_raise)
        assert transaction_root.exists()
        del ctrl

        fresh, fresh_store = _controller(tmp_path)
        runner_after = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                SquadResult.from_state(fresh_store.load())
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", runner_after)

        fresh.run("msg", "banzai")

        completed = fresh_store.load()
        assert runner_after.call_count == 1
        assert PENDING_CONTROLLER_COMPLETION_KEY not in completed
        assert not transaction_root.exists()
        dispatch = completed["last_dispatch"]
        assert dispatch["dispatch_id"] == completion_id
        assert dispatch["manual_phase_run"] is True
        assert dispatch["post_dispatch_complete"] is True
        assert completed["token_usage"] == 0
        assert not (
            fresh._squad_dir / "reasoning-journal.jsonl"
        ).exists()

    @pytest.mark.parametrize(
        ("damage", "expected_code"),
        [
            ("intent_missing", "stage_missing"),
            ("intent_corrupt", "intent_mismatch"),
            ("receipts_missing", "stage_missing"),
            ("receipts_corrupt", "receipts_mismatch"),
        ],
    )
    def test_fresh_controller_retains_corrupt_completion_stage(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        damage: str,
        expected_code: str,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        prepared = _install_empty_routed_completion(ctrl, store)
        filename = (
            "intent.json"
            if damage.startswith("intent")
            else "receipts.json"
        )
        damaged = prepared._transaction_root / filename
        if damage.endswith("missing"):
            damaged.unlink()
        else:
            damaged.write_bytes(b"{not canonical json}\n")
        state = store.load()
        state["controller_completion_failure"] = {
            "unbounded": "corrupt prior diagnostic"
        }
        store.save(state)
        del ctrl
        fresh, fresh_store = _controller(tmp_path)
        runner = MagicMock(
            side_effect=AssertionError(
                "corrupt completion reached phase work"
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", runner)

        fresh.run("msg", "banzai")

        failed = fresh_store.load()
        assert runner.call_count == 0
        assert PENDING_CONTROLLER_COMPLETION_KEY in failed
        assert failed["controller_completion_failure"] == {
            "schema_version": 1,
            "code": expected_code,
            "resume_status": "running",
            "resume_blocked_reason": None,
        }
        assert damaged.exists() is (not damage.endswith("missing"))

    def test_null_publication_authority_cannot_outlive_none_binding(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        _install_empty_routed_completion(ctrl, store)
        state = store.load()
        state[PENDING_EXTERNAL_PUBLICATION_KEY] = None
        store.save(state)
        runner = MagicMock(
            side_effect=AssertionError(
                "mismatched authorities reached phase work"
            )
        )
        monkeypatch.setattr(ctrl, "_run_locked", runner)

        ctrl.run("msg", "banzai")

        failed = store.load()
        assert runner.call_count == 0
        assert PENDING_CONTROLLER_COMPLETION_KEY in failed
        assert PENDING_EXTERNAL_PUBLICATION_KEY in failed
        assert failed[PENDING_EXTERNAL_PUBLICATION_KEY] is None
        assert failed["controller_completion_failure"]["code"] == (
            "intent_mismatch"
        )

    def test_fresh_controller_removes_only_unreferenced_completion_orphan(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        orphan = prepare_controller_completion(
            tmp_path,
            ctrl._squad_dir,
            completion_id=uuid.uuid4().hex,
            origin="routed",
            publication={"kind": "none"},
            route={
                "kind": "routed",
                "from_phase": "phase1-what",
                "to_phase": "phase1-why1",
                "manual_phase_run": False,
                "record_completion": True,
            },
            effect_plan=(),
            checkpoint_prestate={"kind": "none"},
            context_reason="unreferenced test orphan",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        )
        transaction_root = orphan._transaction_root
        del ctrl
        fresh, fresh_store = _controller(tmp_path)
        runner = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                SquadResult.from_state(fresh_store.load())
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", runner)

        fresh.run("msg", "banzai")

        assert runner.call_count == 1
        assert not transaction_root.exists()

    def test_fresh_controller_retains_orphan_for_incomplete_bound_dispatch(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        prepared = _install_empty_routed_completion(ctrl, store)
        transaction_root = prepared._transaction_root
        state = store.load()
        state.pop(PENDING_CONTROLLER_COMPLETION_KEY)
        store.save(state)
        del ctrl
        fresh, fresh_store = _controller(tmp_path)
        runner = MagicMock(
            side_effect=AssertionError(
                "incomplete dispatch was treated as an orphan"
            )
        )
        monkeypatch.setattr(fresh, "_run_locked", runner)

        fresh.run("msg", "banzai")

        assert runner.call_count == 0
        assert transaction_root.exists()

        completed = store.load()
        completed["last_dispatch"]["post_dispatch_complete"] = True
        completed["last_dispatch"][
            "completion_receipts_sha256"
        ] = prepared.marker.receipts_sha256
        store.save(completed)
        del fresh
        resumed_controller, resumed_store = _controller(tmp_path)
        resumed = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                SquadResult.from_state(resumed_store.load())
            )
        )
        monkeypatch.setattr(
            resumed_controller,
            "_run_locked",
            resumed,
        )

        resumed_controller.run("msg", "banzai")

        assert resumed.call_count == 1
        assert not transaction_root.exists()

    def test_route_saved_then_raised_drains_once_without_token_duplication(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ctrl, store = _controller(tmp_path)
        _configure_tasks_lexicon_route(ctrl, store, monkeypatch)
        node = ctrl._graph.get("phase3-tasks-lexicon")
        result = ctrl._executors["deterministic_lexicon"].execute(
            node,
            store,
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase=node.id,
        )
        prepared_result = ctrl._prepare_phase_result(
            node,
            result,
            snapshot,
        )
        with ctrl._defer_routing_provider_usage() as usage:
            usage["tokens"] = 19
            decision = ctrl._coordinate_transition_routing(
                node,
                prepared_result,
                snapshot,
            )
        original_save = store._save_unlocked
        injected = False

        def save_route_then_raise(state):
            nonlocal injected
            saved = original_save(state)
            if (
                not injected
                and PENDING_CONTROLLER_COMPLETION_KEY in state
                and isinstance(state.get("last_dispatch"), dict)
            ):
                injected = True
                raise OSError("injected route save ambiguity")
            return saved

        monkeypatch.setattr(
            store,
            "_save_unlocked",
            save_route_then_raise,
        )
        advance = MagicMock(wraps=store.advance)
        monkeypatch.setattr(store, "advance", advance)

        receipt = ctrl._advance_prepared_result_or_block(
            node,
            decision,
        )

        state = store.load()
        assert injected is True
        assert receipt is not None
        assert advance.call_count == 1
        assert state["token_usage"] == 19
        assert state["last_dispatch"]["post_dispatch_complete"] is True
        assert "controller_contract_error" not in state
        assert "controller_completion_failure" not in state
