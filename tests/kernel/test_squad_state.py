"""Tests for SquadStateStore."""
import errno
import fcntl
import hashlib
import json
import os
import stat
import sys
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from pathlib import PurePath
from threading import Event, Thread
from unittest.mock import patch

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.phase_graph import PhaseGraph, PhaseNode
from harness.controller_state_contracts import (
    ControllerStateContractViolation,
)
from harness.human_input import (
    HumanInputOption,
    HumanInputPolicy,
    HumanInputPolicyRegistry,
    HumanInputResolution,
    PreparedHumanInput,
    controller_safeguard_policies,
)
from harness.prepared_phase_result import PreparedPhaseResult, prepare_phase_result
from harness.recovery_instruction import controller_contract_recovery
from harness.squad_completion import (
    PreparedControllerCompletion,
    load_prepared_controller_completion,
    prepare_controller_completion,
)
from harness.squad_state import (
    StateAdvanceError,
    StateDurabilityError,
    SquadStateStore,
)
from harness.squad_provider import SquadAgentResult
from harness.state_transaction_namespace import (
    PENDING_CONTROLLER_COMPLETION_KEY,
    PENDING_EXTERNAL_PUBLICATION_KEY,
)

DEFINITION = EXT_ROOT / "runtime/workflow/definition.yaml"
PROSAIC_SUBAGENTS = EXT_ROOT / "prosaic/subagents"
VALID_MARKER = {
    "schema_version": 1,
    "transaction_id": "a" * 32,
    "manifest_sha256": "b" * 64,
}
VALID_COMPLETION_MARKER = {
    "schema_version": 1,
    "completion_id": "c" * 32,
    "intent_sha256": "d" * 64,
    "publication_binding_sha256": "e" * 64,
    "receipts_sha256": "f" * 64,
    "origin": "routed",
    "step": "journal",
}
VALID_PRODUCT_INPUT_MUTATION = {
    "schema_version": 1,
    "kind": "controller_update",
    "operation_id": VALID_MARKER["transaction_id"],
    "manifest_sha256": VALID_MARKER["manifest_sha256"],
    "inputs_dir": "runs/r/inputs",
    "old_tree_hash": "sha256:" + "a" * 64,
    "new_tree_hash": "sha256:" + "b" * 64,
    "owned_paths_sha256": "c" * 64,
    "owned_path_count": 1,
    "request_sha256": None,
    "attachment_id": None,
    "added_count": 0,
    "duplicate_count": 0,
}


@pytest.mark.parametrize(
    ("attachment_id", "valid"),
    [
        ("999", True),
        ("1000", True),
        ("123456789012", True),
        ("000", True),
        ("0001", True),
        ("99", False),
        ("1234567890123", False),
        ("12a", False),
        ("+001", False),
        (" 001", False),
    ],
)
def test_product_input_attachment_id_validator_matches_state_schema(
    attachment_id: str,
    valid: bool,
) -> None:
    from harness.state_transaction_namespace import (
        is_valid_product_input_attachment_id,
        validate_product_input_mutation,
    )

    mutation = {
        **VALID_PRODUCT_INPUT_MUTATION,
        "kind": "add_input",
        "request_sha256": "d" * 64,
        "attachment_id": attachment_id,
        "added_count": 1,
    }

    assert is_valid_product_input_attachment_id(attachment_id) is valid
    if valid:
        assert validate_product_input_mutation(mutation) == mutation
    else:
        with pytest.raises(ValueError, match="add-input product input mutation receipt"):
            validate_product_input_mutation(mutation)


def _store(tmp_path: Path) -> SquadStateStore:
    return SquadStateStore(tmp_path / "squad/run-test")


def _raw_result(verdict="DONE", updates=None) -> SquadAgentResult:
    return SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": verdict, "state_updates": updates or {}},
        raw_output="",
        duration_ms=100,
        timed_out=False,
    )


def _result(
    verdict="DONE",
    updates=None,
    *,
    phase_id: str = "init",
    routing_override: str | None = None,
) -> PreparedPhaseResult:
    updates = updates or {}
    return prepare_phase_result(
        PhaseNode(
            id=phase_id,
            type="agent",
            allowed_state_updates=list(updates),
        ),
        _raw_result(verdict, updates),
        controller_updates={},
        routing_override=routing_override,
    )


def _tasks_result(
    *,
    report: object = "tasks-lexicon-report.json",
) -> PreparedPhaseResult:
    node = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS).get("phase3-tasks-lexicon")
    return prepare_phase_result(
        node,
        _raw_result(
            "DONE",
            {
                "tasks_lexicon_action": "proceed",
                "tasks_lexicon_pass": True,
                "tasks_lexicon_attempts": 0,
                "tasks_lexicon_findings": 0,
                "tasks_lexicon_report": report,
            },
        ),
        controller_updates={},
        controller_owns_result_updates=True,
    )


def _advance(
    store: SquadStateStore,
    from_phase: str,
    to_phase: str,
    prepared: PreparedPhaseResult,
    *,
    increment_iteration: bool = False,
    manual_phase_run: bool = False,
    conditional_skip: bool = False,
    checkpoint_policy: str = "none",
    token_usage_delta: int = 0,
    dispatch_id: str | None = None,
    transaction_state_updates: dict[str, object] | None = None,
    transaction_state_removals: object = (),
    human_input: PreparedHumanInput | None = None,
    human_input_initial_status: str | None = None,
):
    snapshot = store.capture_routing_snapshot(expected_phase=from_phase)
    decision = store.prepare_routing_decision(
        prepared,
        snapshot=snapshot,
        from_phase=from_phase,
        to_phase=to_phase,
        increment_iteration=increment_iteration,
        manual_phase_run=manual_phase_run,
        conditional_skip=conditional_skip,
        checkpoint_policy=checkpoint_policy,
        token_usage_delta=token_usage_delta,
        dispatch_id=dispatch_id,
        transaction_state_updates=transaction_state_updates,
        transaction_state_removals=transaction_state_removals,
    )
    return store.advance(
        from_phase,
        to_phase,
        decision,
        human_input=human_input,
        human_input_initial_status=human_input_initial_status,
    )


def _human_input_request(
    *,
    source_kind: str,
    source_state_revision: int,
    phase_id: str = "init",
    producer_id: str | None = None,
) -> PreparedHumanInput:
    if source_kind == "controller_safeguard":
        producer_id = producer_id or "consecutive_why_fails"
        policy = next(
            item
            for item in controller_safeguard_policies()
            if item.producer_id == producer_id
        )
        request = HumanInputPolicyRegistry((policy,)).prepare(
            source_kind=source_kind,
            producer_id=producer_id,
            phase_id=phase_id,
            reason_code=policy.reason_code,
            question=f"{producer_id} requires a routing decision.",
            recommended_answer="Continue with the attested provider result.",
            risk_level="medium",
            source_state_revision=source_state_revision,
        )
        if producer_id == "phase_dispatch_limit":
            candidate = {
                "issue_id": "ISS-001",
                "title": "Bounded controller safeguard",
                "decision_required": "Choose the attested repair.",
                "suggested_option": "Apply the attested repair.",
                "evidence_basis": "The persisted issue evidence is complete.",
            }
            request = replace(
                request,
                recommended_answer=None,
                risk_level=None,
                options=(
                    HumanInputOption(
                        id=candidate["issue_id"],
                        label=(
                            f"{candidate['issue_id']}: "
                            f"{candidate['title']}"
                        ),
                        description=json.dumps(
                            candidate,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        recommended=True,
                        risk_level="medium",
                        next_phase="phase1-what",
                        outcome=None,
                    ),
                ),
                recommended_option_id=candidate["issue_id"],
            )
        return request
    producer_id = producer_id or "init"
    options = (
        (
            HumanInputOption(
                id="approve",
                label="Approve",
                description="Continue to the next phase.",
                recommended=True,
                risk_level="low",
                next_phase="next",
                outcome="approve",
            ),
            HumanInputOption(
                id="reject",
                label="Reject",
                description="Stop for plan revision.",
                recommended=False,
                risk_level="medium",
                next_phase="terminal-blocked",
                outcome="reject",
            ),
        )
        if source_kind == "human_gate"
        else ()
    )
    policy = HumanInputPolicy(
        source_kind=source_kind,
        producer_id=producer_id,
        reason_code="approval_required",
        classification="operational",
        semi_policy="require_human",
        resolution_handler=(
            "gate_outcome"
            if source_kind == "human_gate"
            else "clarification_resume"
        ),
        allow_free_text=source_kind != "human_gate",
        allowed_phase_ids=frozenset({"init", "next"}),
        allowed_target_phases=frozenset({"next", "terminal-blocked"}),
        context_state_keys=("phase",),
        context_paths=(),
        options=options,
    )
    return HumanInputPolicyRegistry((policy,)).prepare(
        source_kind=source_kind,
        producer_id=producer_id,
        phase_id=phase_id,
        reason_code="approval_required",
        question="May the squad continue?",
        recommended_answer=(
            "Continue with the attested provider result."
            if source_kind != "human_gate"
            else None
        ),
        risk_level="low" if source_kind != "human_gate" else None,
        source_state_revision=source_state_revision,
    )


def _seal_provider_human_input_via_advance(
    store: SquadStateStore,
    *,
    source_kind: str = "provider_escalation",
    producer_id: str | None = None,
    from_phase: str = "init",
    to_phase: str = "next",
) -> dict[str, object]:
    before = store.load()
    request = _human_input_request(
        source_kind=source_kind,
        producer_id=producer_id,
        source_state_revision=before["state_revision"],
        phase_id=from_phase,
    )
    _advance(
        store,
        from_phase,
        to_phase,
        _result(
            "DONE",
            {"provider_fact": "attested"},
            phase_id=from_phase,
        ),
        dispatch_id="d" * 32,
        human_input=request,
        human_input_initial_status="pending",
    )
    return store.load()


def _prepare_completion(
    tmp_path: Path,
    store: SquadStateStore,
    *,
    completion_id: str = "c" * 32,
    origin: str = "routed",
    external_publication: bool = False,
    effect_plan: tuple[str, ...] = ("journal", "timing"),
    from_phase: str = "init",
    to_phase: str = "next",
) -> PreparedControllerCompletion:
    route = (
        {
            "kind": "routed",
            "from_phase": from_phase,
            "to_phase": to_phase,
            "manual_phase_run": False,
            "record_completion": True,
        }
        if origin == "routed"
        else {
            "kind": "terminal",
            "terminal_phase": from_phase,
        }
    )
    publication = (
        {"kind": "external", "marker": VALID_MARKER}
        if external_publication
        else {"kind": "none"}
    )
    return prepare_controller_completion(
        tmp_path,
        store.squad_dir,
        completion_id=completion_id,
        origin=origin,
        publication=publication,
        route=route,
        effect_plan=effect_plan,
        checkpoint_prestate={"kind": "none"},
        context_reason="state transition test",
        mine_phase_a="mining" in effect_plan,
        judgment_payload_sha256=(),
        judgments=(),
    )


def _commit_routed_completion(
    store: SquadStateStore,
    prepared: PreparedControllerCompletion,
) -> None:
    transaction_updates = {
        PENDING_CONTROLLER_COMPLETION_KEY: prepared.marker.to_dict(),
    }
    if prepared.intent.publication["kind"] == "external":
        transaction_updates[PENDING_EXTERNAL_PUBLICATION_KEY] = VALID_MARKER
    route = prepared.intent.route
    _advance(
        store,
        route["from_phase"],
        route["to_phase"],
        _result("DONE", phase_id=route["from_phase"]),
        dispatch_id=prepared.marker.completion_id,
        transaction_state_updates=transaction_updates,
    )


def _rewrite_completion_receipts(
    tmp_path: Path,
    store: SquadStateStore,
    prepared: PreparedControllerCompletion,
    effects: dict[str, object],
) -> PreparedControllerCompletion:
    receipt_document = {
        "schema_version": 1,
        "completion_id": prepared.marker.completion_id,
        "effects": effects,
    }
    content = (
        json.dumps(
            receipt_document,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    (
        store.squad_dir
        / ".completion-outbox"
        / prepared.marker.completion_id
        / "receipts.json"
    ).write_bytes(content)
    return load_prepared_controller_completion(
        tmp_path,
        store.squad_dir,
        prepared.marker,
    )


class TestSquadStateStore:
    def test_load_returns_empty_when_no_file(self, tmp_path):
        store = _store(tmp_path)
        assert store.load() == {}

    def test_initialize_writes_state(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("run-001", "greenfield", "do stuff", 500_000, "init")
        state = store.load()
        assert state["run_id"] == "run-001"
        assert state["phase"] == "init"
        assert state["status"] == "running"
        assert state["token_budget"] == 500_000
        assert state["mode"] == "greenfield"
        assert state["autonomy_mode"] == "semi"
        assert state["spec_authoring_mode"] == "proportional"

    def test_initialize_can_store_perfectionist_spec_authoring_mode(self, tmp_path):
        store = _store(tmp_path)
        store.initialize(
            "run-001",
            "greenfield",
            "do stuff",
            500_000,
            "init",
            spec_authoring_mode="perfectionist",
        )

        state = store.load()
        assert state["spec_authoring_mode"] == "perfectionist"
        assert "phase1_quality_repair" not in state

    def test_initialize_adds_proportional_quality_repair_state(self, tmp_path):
        store = _store(tmp_path)

        store.initialize("run-001", "greenfield", "do stuff", 500_000, "init")

        repair = store.load()["phase1_quality_repair"]
        assert repair["automatic_limit"] == 3
        assert repair["automatic_consumed"] == 0
        assert repair["extension_limit"] == 1
        assert repair["extension_consumed"] == 0

    def test_initialize_can_store_project_and_autonomy_modes_separately(self, tmp_path):
        store = _store(tmp_path)
        store.initialize(
            "run-001",
            "brownfield",
            "do stuff",
            500_000,
            "init",
            autonomy_mode="banzai",
        )
        state = store.load()
        assert state["mode"] == "brownfield"
        assert state["autonomy_mode"] == "banzai"

    def test_current_phase_returns_init_after_initialize(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        assert store.current_phase() == "init"

    def test_current_phase_returns_init_when_no_state(self, tmp_path):
        assert _store(tmp_path).current_phase() == "init"

    def test_routing_snapshot_is_immutable_and_rejects_same_phase_revision_change(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "repair")
        snapshot = store.capture_routing_snapshot(expected_phase="repair")
        detached = snapshot.state
        detached["route_flag"] = "tampered-copy"

        changed = store.load()
        changed["route_flag"] = "new-live-value"
        store.save(changed)
        before = store.load()

        assert "route_flag" not in snapshot.state
        with pytest.raises(StateAdvanceError) as raised:
            store.prepare_routing_decision(
                _result("DONE", phase_id="repair"),
                snapshot=snapshot,
                from_phase="repair",
                to_phase="next",
            )

        assert raised.value.validator == "stale_state"
        assert store.load() == before

    def test_unchanged_routing_snapshot_still_allows_valid_self_loop(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "repair")
        snapshot = store.capture_routing_snapshot(expected_phase="repair")
        decision = store.prepare_routing_decision(
            _result("DONE", phase_id="repair"),
            snapshot=snapshot,
            from_phase="repair",
            to_phase="repair",
        )

        receipt = store.advance("repair", "repair", decision)

        assert receipt.from_phase == receipt.to_phase == "repair"
        assert store.load()["phase"] == "repair"

    def test_old_state_without_pending_publication_still_advances(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")

        _advance(
            store,
            "init",
            "phase1-discover",
            _result("DONE"),
        )

        advanced = store.load()
        assert advanced["phase"] == "phase1-discover"
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in advanced

    def test_trusted_pending_publication_marker_commits_with_advance(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")

        _advance(
            store,
            "init",
            "phase1-discover",
            _result("DONE"),
            transaction_state_updates={
                PENDING_EXTERNAL_PUBLICATION_KEY: VALID_MARKER
            },
        )

        assert store.load()[PENDING_EXTERNAL_PUBLICATION_KEY] == VALID_MARKER

    def test_invalid_pending_publication_marker_cannot_advance(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        before = store.load()

        with pytest.raises(
            (ControllerStateContractViolation, StateAdvanceError)
        ):
            _advance(
                store,
                "init",
                "phase1-discover",
                _result("DONE"),
                transaction_state_updates={
                    PENDING_EXTERNAL_PUBLICATION_KEY: {
                        **VALID_MARKER,
                        "schema_version": True,
                    }
                },
            )

        assert store.load() == before

    def test_pending_publication_marker_cannot_be_removed_by_advance(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        state = store.load()
        state[PENDING_EXTERNAL_PUBLICATION_KEY] = VALID_MARKER
        store.save(state)
        before = store.load()

        with pytest.raises(ControllerStateContractViolation) as raised:
            _advance(
                store,
                "init",
                "phase1-discover",
                _result("DONE"),
                transaction_state_removals={
                    PENDING_EXTERNAL_PUBLICATION_KEY
                },
            )

        assert raised.value.validator == "ownership"
        assert raised.value.json_path == (
            "$.transaction_state_removals."
            f"{PENDING_EXTERNAL_PUBLICATION_KEY}"
        )
        assert store.load() == before

    def test_product_inputs_contract_cannot_be_removed_by_advance(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "init",
            product_inputs={"tree_hash": "sha256:" + "a" * 64},
        )
        before = store.load()

        with pytest.raises(ControllerStateContractViolation) as raised:
            _advance(
                store,
                "init",
                "phase1-discover",
                _result("DONE"),
                transaction_state_removals={"product_inputs"},
            )

        assert raised.value.validator == "ownership"
        assert raised.value.json_path == "$.transaction_state_removals.product_inputs"
        assert store.load() == before

    @pytest.mark.parametrize("receipt", [None, {**VALID_PRODUCT_INPUT_MUTATION, "owned_path_count": 0}])
    def test_product_inputs_update_requires_exact_mutation_receipt_without_write(
        self,
        tmp_path,
        receipt,
    ):
        store = _store(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "init",
            product_inputs={
                "inputs_dir": "runs/r/inputs",
                "tree_hash": "sha256:" + "a" * 64,
            },
        )
        before = store.load()
        updates = {
            PENDING_EXTERNAL_PUBLICATION_KEY: VALID_MARKER,
            "product_inputs": {
                "inputs_dir": "runs/r/inputs",
                "tree_hash": "sha256:" + "b" * 64,
            },
        }
        if receipt is not None:
            updates["product_input_mutation"] = receipt

        with pytest.raises((ControllerStateContractViolation, StateAdvanceError)):
            _advance(
                store,
                "init",
                "phase1-discover",
                _result("DONE"),
                transaction_state_updates=updates,
            )

        assert store.load() == before

    def test_product_inputs_update_accepts_exact_mutation_receipt(self, tmp_path):
        store = _store(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "init",
            product_inputs={
                "inputs_dir": "runs/r/inputs",
                "tree_hash": "sha256:" + "a" * 64,
            },
        )

        _advance(
            store,
            "init",
            "phase1-discover",
            _result("DONE"),
            transaction_state_updates={
                PENDING_EXTERNAL_PUBLICATION_KEY: VALID_MARKER,
                "product_inputs": {
                    "inputs_dir": "runs/r/inputs",
                    "tree_hash": "sha256:" + "b" * 64,
                },
                "product_input_mutation": VALID_PRODUCT_INPUT_MUTATION,
            },
        )

        state = store.load()
        assert state["product_inputs"]["tree_hash"] == "sha256:" + "b" * 64
        assert state["product_input_mutation"] == VALID_PRODUCT_INPUT_MUTATION

    def test_record_external_publication_failure_blocks_and_preserves_marker(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        state = store.load()
        state[PENDING_EXTERNAL_PUBLICATION_KEY] = VALID_MARKER
        store.save(state)

        store.record_external_publication_failure(
            VALID_MARKER,
            "target_drift",
        )

        failed = store.load()
        assert failed["status"] == "blocked"
        assert failed["blocked_reason"] == "external_publication_pending"
        assert failed["external_publication_failure"]["code"] == "target_drift"
        assert failed[PENDING_EXTERNAL_PUBLICATION_KEY] == VALID_MARKER
        assert failed["external_publication_failure"] == {
            "schema_version": 1,
            "code": "target_drift",
            "resume_status": "running",
            "resume_blocked_reason": None,
        }

    def test_repeated_external_publication_failure_updates_only_bounded_code(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        state = store.load()
        state.update(
            {
                "status": "blocked",
                "blocked_reason": "needs_judgment",
                PENDING_EXTERNAL_PUBLICATION_KEY: VALID_MARKER,
            }
        )
        store.save(state)
        store.record_external_publication_failure(
            VALID_MARKER,
            "stage_missing",
        )
        original_diagnostic = store.load()["external_publication_failure"]

        store.record_external_publication_failure(
            VALID_MARKER,
            "publish_io",
        )

        repeated = store.load()
        assert repeated["external_publication_failure"] == {
            **original_diagnostic,
            "code": "publish_io",
        }
        assert repeated["status"] == "blocked"
        assert repeated["blocked_reason"] == "external_publication_pending"

    def test_external_publication_failure_replaces_corrupt_diagnostic(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        state = store.load()
        state.update(
            {
                PENDING_EXTERNAL_PUBLICATION_KEY: VALID_MARKER,
                "status": "blocked",
                "blocked_reason": "external_publication_pending",
                "external_publication_failure": {"raw": "corrupt"},
            }
        )
        store.save(state)

        store.record_external_publication_failure(
            VALID_MARKER,
            "stage_missing",
        )

        assert store.load()["external_publication_failure"] == {
            "schema_version": 1,
            "code": "stage_missing",
            "resume_status": "running",
            "resume_blocked_reason": None,
        }

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
    def test_malformed_external_publication_failure_uses_exact_raw_marker_cas(
        self,
        tmp_path,
        marker,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        state = store.load()
        state[PENDING_EXTERNAL_PUBLICATION_KEY] = marker
        store.save(state)

        store.record_malformed_external_publication_failure(marker)

        failed = store.load()
        assert failed[PENDING_EXTERNAL_PUBLICATION_KEY] == marker
        assert failed["status"] == "blocked"
        assert failed["blocked_reason"] == "external_publication_pending"
        assert failed["external_publication_failure"] == {
            "schema_version": 1,
            "code": "manifest_invalid",
            "resume_status": "running",
            "resume_blocked_reason": None,
        }

    def test_malformed_external_publication_failure_rejects_marker_mismatch(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        malformed = {
            "schema_version": 1,
            "transaction_id": "bad",
            "manifest_sha256": "b" * 64,
        }
        state = store.load()
        state[PENDING_EXTERNAL_PUBLICATION_KEY] = malformed
        store.save(state)
        before = store.load()

        with pytest.raises(StateAdvanceError):
            store.record_malformed_external_publication_failure(None)

        assert store.load() == before

    def test_malformed_external_publication_replaces_corrupt_diagnostic(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        malformed = {
            "schema_version": 1,
            "transaction_id": "bad",
            "manifest_sha256": "b" * 64,
        }
        state = store.load()
        state.update(
            {
                PENDING_EXTERNAL_PUBLICATION_KEY: malformed,
                "status": "blocked",
                "blocked_reason": "external_publication_pending",
                "external_publication_failure": {"raw": "corrupt"},
            }
        )
        store.save(state)

        store.record_malformed_external_publication_failure(malformed)

        assert store.load()["external_publication_failure"] == {
            "schema_version": 1,
            "code": "manifest_invalid",
            "resume_status": "running",
            "resume_blocked_reason": None,
        }

    @pytest.mark.parametrize(
        "method_name,args",
        [
            (
                "record_external_publication_failure",
                ("target_drift",),
            ),
            ("complete_external_publication", ()),
        ],
    )
    def test_external_publication_marker_mismatch_cannot_record_or_clear(
        self,
        tmp_path,
        method_name,
        args,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        state = store.load()
        state[PENDING_EXTERNAL_PUBLICATION_KEY] = VALID_MARKER
        store.save(state)
        before = store.load()
        mismatched = {
            **VALID_MARKER,
            "transaction_id": "c" * 32,
        }

        with pytest.raises(StateAdvanceError):
            getattr(store, method_name)(mismatched, *args)

        assert store.load() == before

    @pytest.mark.parametrize(
        "code",
        [
            "unknown",
            True,
            "",
            "manifest-invalid",
        ],
    )
    def test_external_publication_failure_rejects_unbounded_code(
        self,
        tmp_path,
        code,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        state = store.load()
        state[PENDING_EXTERNAL_PUBLICATION_KEY] = VALID_MARKER
        store.save(state)
        before = store.load()

        with pytest.raises((ValueError, StateAdvanceError)):
            store.record_external_publication_failure(VALID_MARKER, code)

        assert store.load() == before

    def test_complete_external_publication_restores_lifecycle_in_one_save(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        state = store.load()
        state.update(
            {
                "status": "blocked",
                "blocked_reason": "needs_judgment",
                PENDING_EXTERNAL_PUBLICATION_KEY: VALID_MARKER,
            }
        )
        store.save(state)
        store.record_external_publication_failure(
            VALID_MARKER,
            "stage_missing",
        )

        with patch.object(
            store,
            "_save_unlocked",
            wraps=store._save_unlocked,
        ) as save:
            store.complete_external_publication(VALID_MARKER)

        completed = store.load()
        assert save.call_count == 1
        assert completed["status"] == "blocked"
        assert completed["blocked_reason"] == "needs_judgment"
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in completed
        assert "external_publication_failure" not in completed

    def test_legacy_publication_clear_rejects_coupled_completion_marker(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        completion_marker = {
            **VALID_COMPLETION_MARKER,
            "step": "awaiting_publication",
        }
        state = store.load()
        state[PENDING_EXTERNAL_PUBLICATION_KEY] = VALID_MARKER
        state[PENDING_CONTROLLER_COMPLETION_KEY] = completion_marker
        store.save(state)
        before = store.load()

        with pytest.raises(StateAdvanceError) as raised:
            store.complete_external_publication(VALID_MARKER)

        assert raised.value.validator == "completion_binding"
        assert store.load() == before

    def test_begin_external_publication_exact_cas_preserves_lifecycle(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "DONE")
        state = store.load()
        state["status"] = "done"
        store.save(state)
        snapshot = store.capture_routing_snapshot(expected_phase="DONE")
        before = store.load()

        with patch.object(
            store,
            "_save_unlocked",
            wraps=store._save_unlocked,
        ) as save:
            store.begin_external_publication(
                VALID_MARKER,
                snapshot=snapshot,
                state_updates={
                    "published_spec_dir": "specs/001-demo",
                },
            )

        started = store.load()
        assert save.call_count == 1
        assert started[PENDING_EXTERNAL_PUBLICATION_KEY] == VALID_MARKER
        assert started["published_spec_dir"] == "specs/001-demo"
        assert started["phase"] == before["phase"]
        assert started["status"] == before["status"]
        assert started.get("blocked_reason") == before.get("blocked_reason")

    def test_begin_external_publication_rejects_stale_snapshot_without_marker(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "DONE")
        snapshot = store.capture_routing_snapshot(expected_phase="DONE")
        concurrent = store.load()
        concurrent["concurrent_marker"] = "kept"
        store.save(concurrent)
        before = store.load()

        with pytest.raises(StateAdvanceError) as raised:
            store.begin_external_publication(
                VALID_MARKER,
                snapshot=snapshot,
            )

        assert raised.value.validator == "stale_state"
        assert store.load() == before
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in store.load()

    def test_begin_external_publication_save_failure_leaves_marker_absent(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "DONE")
        snapshot = store.capture_routing_snapshot(expected_phase="DONE")
        before = store.load()

        with patch.object(
            store,
            "_save_unlocked",
            side_effect=OSError("injected save failure"),
        ):
            with pytest.raises(StateAdvanceError) as raised:
                store.begin_external_publication(
                    VALID_MARKER,
                    snapshot=snapshot,
                )

        assert raised.value.validator == "save"
        assert store.load() == before
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in store.load()

    def test_advance_save_failure_never_durably_installs_publication_marker(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "repair")
        snapshot = store.capture_routing_snapshot(expected_phase="repair")
        decision = store.prepare_routing_decision(
            _result("DONE", phase_id="repair"),
            snapshot=snapshot,
            from_phase="repair",
            to_phase="next",
            transaction_state_updates={
                PENDING_EXTERNAL_PUBLICATION_KEY: VALID_MARKER,
            },
        )
        before = store.load()

        with patch.object(
            store,
            "_save_unlocked",
            side_effect=OSError("injected save failure"),
        ):
            with pytest.raises(StateAdvanceError) as raised:
                store.advance("repair", "next", decision)

        assert raised.value.validator == "save"
        assert store.load() == before
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in store.load()

    def test_snapshot_bound_failure_diagnostic_rejects_same_phase_new_revision(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "repair")
        snapshot = store.capture_routing_snapshot(expected_phase="repair")

        concurrent = store.load()
        concurrent["concurrent_marker"] = "published"
        store.save(concurrent)
        before = store.load()

        persisted = store.merge_advance_failure_diagnostic(
            from_phase="repair",
            expected_state_revision=snapshot.state_revision,
            expected_previous_dispatch_sha256=(
                snapshot.previous_dispatch_sha256
            ),
            updates={
                "status": "blocked",
                "controller_contract_error": {"forged": False},
            },
        )

        assert persisted is False
        assert store.load() == before
        assert "controller_contract_error" not in store.load()

    def test_sealed_token_usage_delta_commits_with_successful_advance(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        state = store.load()
        state["token_usage"] = 4
        store.save(state)

        _advance(
            store,
            "init",
            "next",
            _result("DONE"),
            token_usage_delta=13,
        )

        assert store.load()["token_usage"] == 17

    def test_advance_updates_phase(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        _advance(store, "init", "phase1-discover", _result())
        assert store.current_phase() == "phase1-discover"

    def test_preparation_rejects_transaction_owned_phase_update(self):
        with pytest.raises(ControllerStateContractViolation) as raised:
            _result(
                "DONE",
                {"phase": "attacker-selected"},
                phase_id="init",
            )

        assert raised.value.validator == "ownership"
        assert raised.value.json_path == "$.state_updates.phase"

    def test_stale_public_save_cannot_overwrite_successful_advance(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        stale = store.load()
        _advance(store, "init", "phase1-discover", _result())
        published = store.load()

        stale["cancel_requested"] = True
        with pytest.raises(StateAdvanceError) as raised:
            store.save(stale)

        assert raised.value.validator == "stale_state"
        assert store.load() == published

    def test_advance_rejects_persisted_phase_mismatch_without_write(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        before = store.load()

        with patch.object(store, "save", wraps=store.save) as save:
            with pytest.raises(StateAdvanceError) as raised:
                _advance(
                    store,
                    "phase1-constitution",
                    "phase1-what",
                    _result("DONE", phase_id="phase1-constitution"),
                )

        assert raised.value.validator == "stale_state"
        assert save.call_count == 0
        assert store.load() == before

    def test_authentic_prepared_result_cannot_replay_after_phase_progress(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        original = _result("DONE", phase_id="init")
        snapshot = store.capture_routing_snapshot(expected_phase="init")
        original_decision = store.prepare_routing_decision(
            original,
            snapshot=snapshot,
            from_phase="init",
            to_phase="phase1-discover",
        )
        store.advance("init", "phase1-discover", original_decision)
        _advance(
            store,
            "phase1-discover",
            "phase1-why1",
            _result("DONE", phase_id="phase1-discover"),
        )
        before_replay = store.load()

        with pytest.raises(StateAdvanceError) as raised:
            store.advance(
                "init",
                "phase1-discover",
                original_decision,
            )

        assert raised.value.validator == "stale_state"
        assert store.load() == before_replay

    def test_stale_advance_rejects_before_any_state_commit(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "repair")
        snapshot = store.capture_routing_snapshot(expected_phase="repair")
        decision = store.prepare_routing_decision(
            _result("DONE", phase_id="repair"),
            snapshot=snapshot,
            from_phase="repair",
            to_phase="next",
        )
        concurrent = store.load()
        concurrent["winner_marker"] = True
        store.save(concurrent)

        with pytest.raises(StateAdvanceError) as raised:
            store.advance(
                "repair",
                "next",
                decision,
            )

        assert raised.value.validator == "stale_state"
        assert store.load()["winner_marker"] is True

    def test_advance_exposes_no_mutating_before_commit_hook(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "repair")
        snapshot = store.capture_routing_snapshot(expected_phase="repair")
        decision = store.prepare_routing_decision(
            _result("DONE", phase_id="repair"),
            snapshot=snapshot,
            from_phase="repair",
            to_phase="next",
        )
        before = store.load()
        side_effects: list[str] = []

        with pytest.raises(TypeError, match="before_commit"):
            store.advance(
                "repair",
                "next",
                decision,
                before_commit=lambda: side_effects.append("published"),
            )

        assert side_effects == []
        assert store.load() == before

    def test_self_loop_replay_is_rejected_but_new_current_result_advances(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "repair")
        original = _result("DONE", phase_id="repair")
        snapshot = store.capture_routing_snapshot(expected_phase="repair")
        original_decision = store.prepare_routing_decision(
            original,
            snapshot=snapshot,
            from_phase="repair",
            to_phase="repair",
        )
        first = store.advance("repair", "repair", original_decision)
        after_first = store.load()

        with pytest.raises(StateAdvanceError) as raised:
            store.advance("repair", "repair", original_decision)

        assert raised.value.validator == "stale_state"
        assert store.load() == after_first

        current = _result("DONE", phase_id="repair")
        second = _advance(store, "repair", "repair", current)
        assert second.completed_at != first.completed_at
        assert store.load()["phase"] == "repair"
        assert store.load()["state_revision"] > after_first["state_revision"]

    def test_advance_writes_last_dispatch(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        _advance(store, "init", "phase1-discover", _result("DONE"))
        ld = store.load()["last_dispatch"]
        assert ld["phase_id"] == "init"
        assert ld["verdict"] == "DONE"

    def test_advance_persists_attested_completion_dispatch_binding(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")

        receipt = _advance(
            store,
            "init",
            "next",
            _result("DONE"),
            dispatch_id=VALID_COMPLETION_MARKER["completion_id"],
            transaction_state_updates={
                PENDING_CONTROLLER_COMPLETION_KEY: (
                    VALID_COMPLETION_MARKER
                )
            },
        )

        state = store.load()
        assert receipt.dispatch_id == VALID_COMPLETION_MARKER["completion_id"]
        assert state[PENDING_CONTROLLER_COMPLETION_KEY] == (
            VALID_COMPLETION_MARKER
        )
        assert state["last_dispatch"][
            "dispatch_id"
        ] == VALID_COMPLETION_MARKER["completion_id"]
        assert state["last_dispatch"]["post_dispatch_complete"] is False
        assert state["last_dispatch"]["completion_intent_sha256"] == (
            VALID_COMPLETION_MARKER["intent_sha256"]
        )
        assert state["last_dispatch"]["completion_origin"] == "routed"
        assert state["last_dispatch"][
            "completion_publication_binding_sha256"
        ] == VALID_COMPLETION_MARKER["publication_binding_sha256"]

    def test_advance_without_completion_marker_remains_legacy_complete(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")

        receipt = _advance(
            store,
            "init",
            "next",
            _result("DONE"),
            dispatch_id="1" * 32,
        )

        state = store.load()
        assert receipt.dispatch_id == "1" * 32
        assert state["last_dispatch"]["dispatch_id"] == "1" * 32
        assert "post_dispatch_complete" not in state["last_dispatch"]

    def test_advance_commits_publication_and_completion_markers_together(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        completion_marker = {
            **VALID_COMPLETION_MARKER,
            "step": "awaiting_publication",
        }

        _advance(
            store,
            "init",
            "next",
            _result("DONE"),
            dispatch_id=completion_marker["completion_id"],
            transaction_state_updates={
                PENDING_EXTERNAL_PUBLICATION_KEY: VALID_MARKER,
                PENDING_CONTROLLER_COMPLETION_KEY: completion_marker,
            },
        )

        state = store.load()
        assert state[PENDING_EXTERNAL_PUBLICATION_KEY] == VALID_MARKER
        assert state[PENDING_CONTROLLER_COMPLETION_KEY] == completion_marker

    def test_no_publication_completion_starts_at_first_bound_effect(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        prepared = _prepare_completion(tmp_path, store)

        _commit_routed_completion(store, prepared)

        state = store.load()
        assert prepared.marker.step == "journal"
        assert state[PENDING_CONTROLLER_COMPLETION_KEY] == (
            prepared.marker.to_dict()
        )
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in state

    def test_publication_handoff_restores_lifecycle_and_advances_once(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        prepared = _prepare_completion(
            tmp_path,
            store,
            external_publication=True,
        )
        _commit_routed_completion(store, prepared)
        store.record_external_publication_failure(
            VALID_MARKER,
            "stage_missing",
        )

        with patch.object(
            store,
            "_save_unlocked",
            wraps=store._save_unlocked,
        ) as save:
            store.handoff_external_publication(VALID_MARKER, prepared)

        state = store.load()
        assert save.call_count == 1
        assert PENDING_EXTERNAL_PUBLICATION_KEY not in state
        assert "external_publication_failure" not in state
        assert state[PENDING_CONTROLLER_COMPLETION_KEY] == {
            **prepared.marker.to_dict(),
            "step": "journal",
        }
        assert state["status"] == "running"
        assert "blocked_reason" not in state

    def test_controller_completion_advances_only_with_one_ahead_receipt(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        prepared = _prepare_completion(tmp_path, store)
        _commit_routed_completion(store, prepared)
        before = store.load()

        with pytest.raises(StateAdvanceError):
            store.advance_controller_completion(prepared)
        assert store.load() == before

        one_ahead = _rewrite_completion_receipts(
            tmp_path,
            store,
            prepared,
            {"journal": {"schema_version": 1}},
        )
        store.advance_controller_completion(one_ahead)

        state = store.load()
        receipts_path = (
            store.squad_dir
            / ".completion-outbox"
            / prepared.marker.completion_id
            / "receipts.json"
        )
        assert state[PENDING_CONTROLLER_COMPLETION_KEY] == {
            **prepared.marker.to_dict(),
            "receipts_sha256": hashlib.sha256(
                receipts_path.read_bytes()
            ).hexdigest(),
            "step": "timing",
        }
        after = store.load()
        with pytest.raises(StateAdvanceError):
            store.advance_controller_completion(one_ahead)
        assert store.load() == after

    def test_versioned_controller_completion_advances_with_bound_policy(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        state = store.load()
        state["checkpoint_policy_version"] = 2
        state["phase_completion_outcomes"] = []
        store.save(state)
        prepared = prepare_controller_completion(
            tmp_path,
            store.squad_dir,
            completion_id="c" * 32,
            origin="routed",
            publication={"kind": "none"},
            route={
                "kind": "routed",
                "from_phase": "init",
                "to_phase": "next",
                "manual_phase_run": False,
                "record_completion": True,
                "checkpoint_policy_version": 2,
                "checkpoint_policy": "none",
                "rewind_policy": "none",
            },
            effect_plan=("journal",),
            checkpoint_prestate={"kind": "none"},
            context_reason="versioned state transition test",
            mine_phase_a=False,
            judgment_payload_sha256=(),
            judgments=(),
        )
        _commit_routed_completion(store, prepared)
        one_ahead = _rewrite_completion_receipts(
            tmp_path,
            store,
            prepared,
            {"journal": {"schema_version": 1}},
        )

        store.advance_controller_completion(one_ahead)

        assert store.load()[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == (
            "complete"
        )

    def test_routed_controller_completion_final_clear_is_exact(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        prepared = _prepare_completion(
            tmp_path,
            store,
            effect_plan=("journal",),
        )
        _commit_routed_completion(store, prepared)
        before = store.load()

        with pytest.raises(StateAdvanceError):
            store.complete_controller_completion(prepared)
        assert store.load() == before

        one_ahead = _rewrite_completion_receipts(
            tmp_path,
            store,
            prepared,
            {"journal": {"schema_version": 1}},
        )
        store.advance_controller_completion(one_ahead)
        completed_marker = store.load()[PENDING_CONTROLLER_COMPLETION_KEY]
        completed = load_prepared_controller_completion(
            tmp_path,
            store.squad_dir,
            completed_marker,
        )
        store.complete_controller_completion(completed)

        state = store.load()
        assert PENDING_CONTROLLER_COMPLETION_KEY not in state
        assert state["last_dispatch"]["post_dispatch_complete"] is True
        assert state["last_dispatch"]["completion_intent_sha256"] == (
            completed.marker.intent_sha256
        )
        assert state["last_dispatch"]["completion_receipts_sha256"] == (
            completed.marker.receipts_sha256
        )
        assert state["last_dispatch"][
            "completed_publication_binding_sha256"
        ] == completed.marker.publication_binding_sha256

    def test_terminal_controller_completion_writes_bounded_receipt_and_done(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "DONE")
        prepared = _prepare_completion(
            tmp_path,
            store,
            origin="terminal",
            effect_plan=(),
            from_phase="DONE",
        )
        state = store.load()
        state["status"] = "blocked"
        state["blocked_reason"] = "terminal_reconciliation"
        state[PENDING_CONTROLLER_COMPLETION_KEY] = (
            prepared.marker.to_dict()
        )
        store.save(state)

        store.complete_controller_completion(prepared)

        completed = store.load()
        assert completed["status"] == "done"
        assert "blocked_reason" not in completed
        assert PENDING_CONTROLLER_COMPLETION_KEY not in completed
        assert completed["last_terminal_completion"] == {
            "schema_version": 1,
            "completion_id": prepared.marker.completion_id,
            "intent_sha256": prepared.marker.intent_sha256,
            "receipts_sha256": prepared.marker.receipts_sha256,
            "publication_binding_sha256": (
                prepared.marker.publication_binding_sha256
            ),
            "terminal_phase": "DONE",
        }

    def test_terminal_retarget_completion_adopts_only_a_verified_receipt(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "DONE")
        prepared = _prepare_completion(
            tmp_path,
            store,
            origin="terminal",
            effect_plan=("mining", "retarget"),
            from_phase="DONE",
        )
        state = store.load()
        state["spec_id"] = "001-demo"
        state["retarget"] = {
            "status": "finalizing",
            "revision_id": "retarget-1",
            "checkpoint_commit": "b" * 40,
            "memory_excluded": True,
        }
        state[PENDING_CONTROLLER_COMPLETION_KEY] = prepared.marker.to_dict()
        store.save(state)
        receipt = {
            "completion_id": "c" * 32,
            "replacement_commit": "a" * 40,
            "status": "complete",
        }
        mined = _rewrite_completion_receipts(
            tmp_path,
            store,
            prepared,
            {"mining": {"status": "not_applicable"}},
        )
        store.advance_controller_completion(mined)
        retarget_marker = store.load()[PENDING_CONTROLLER_COMPLETION_KEY]
        retarget_prepared = load_prepared_controller_completion(
            tmp_path, store.squad_dir, retarget_marker
        )
        complete_receipts = _rewrite_completion_receipts(
            tmp_path,
            store,
            retarget_prepared,
            {"mining": {"status": "not_applicable"}, "retarget": receipt},
        )
        store.advance_controller_completion(complete_receipts)
        completed = load_prepared_controller_completion(
            tmp_path,
            store.squad_dir,
            store.load()[PENDING_CONTROLLER_COMPLETION_KEY],
        )
        monkeypatch.setattr(
            "echelon.spec_retarget_finalization.verify_retarget_finalization_receipt",
            lambda *_args: receipt,
        )

        store.complete_controller_completion(completed)

        retarget = store.load()["retarget"]
        assert retarget["status"] == "complete"
        assert retarget["replacement_commit"] == "a" * 40
        assert retarget["finalization_receipt"] == receipt
        assert retarget["comparison_pending_completion_id"] == "c" * 32
        assert "memory_excluded" not in retarget

    def test_terminal_controller_completion_records_reconciled_inventories(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "DONE")
        prepared = _prepare_completion(
            tmp_path,
            store,
            origin="terminal",
            effect_plan=(),
            from_phase="DONE",
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase="DONE",
        )
        store.begin_terminal_controller_completion(
            prepared,
            snapshot=snapshot,
        )

        store.complete_controller_completion(
            prepared,
            phase_a_active_source_sha256="1" * 64,
            phase_a_published_postimage_sha256="2" * 64,
        )

        terminal = store.load()["last_terminal_completion"]
        assert terminal["phase_a_active_source_sha256"] == "1" * 64
        assert (
            terminal["phase_a_published_postimage_sha256"]
            == "2" * 64
        )

    @pytest.mark.parametrize("external_publication", [False, True])
    def test_terminal_controller_completion_begins_with_one_atomic_save(
        self,
        tmp_path,
        external_publication,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "DONE")
        prepared = _prepare_completion(
            tmp_path,
            store,
            origin="terminal",
            external_publication=external_publication,
            effect_plan=(),
            from_phase="DONE",
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase="DONE",
        )

        with patch.object(
            store,
            "_save_unlocked",
            wraps=store._save_unlocked,
        ) as save:
            store.begin_terminal_controller_completion(
                prepared,
                snapshot=snapshot,
                state_updates={"published_spec_dir": "specs/001-demo"},
            )

        state = store.load()
        assert save.call_count == 1
        assert state["phase"] == "DONE"
        assert state["published_spec_dir"] == "specs/001-demo"
        assert state[PENDING_CONTROLLER_COMPLETION_KEY] == (
            prepared.marker.to_dict()
        )
        if external_publication:
            assert state[PENDING_EXTERNAL_PUBLICATION_KEY] == VALID_MARKER
        else:
            assert PENDING_EXTERNAL_PUBLICATION_KEY not in state

    def test_terminal_controller_completion_begin_resolves_saved_then_raised(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "DONE")
        prepared = _prepare_completion(
            tmp_path,
            store,
            origin="terminal",
            external_publication=True,
            effect_plan=(),
            from_phase="DONE",
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase="DONE",
        )
        original_save = store._save_unlocked

        def save_then_raise(state):
            original_save(state)
            raise OSError("injected save ambiguity")

        with patch.object(
            store,
            "_save_unlocked",
            side_effect=save_then_raise,
        ):
            store.begin_terminal_controller_completion(
                prepared,
                snapshot=snapshot,
            )

        state = store.load()
        assert state[PENDING_CONTROLLER_COMPLETION_KEY] == (
            prepared.marker.to_dict()
        )
        assert state[PENDING_EXTERNAL_PUBLICATION_KEY] == VALID_MARKER

    def test_phase4_completion_records_exact_inventory_digests(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase4-document",
        )
        prepared = _prepare_completion(
            tmp_path,
            store,
            effect_plan=(),
            from_phase="phase4-document",
            to_phase="DONE",
        )
        _commit_routed_completion(store, prepared)

        store.complete_controller_completion(
            prepared,
            phase_a_active_source_sha256="1" * 64,
            phase_a_published_postimage_sha256="2" * 64,
        )

        state = store.load()
        assert state["phase_a_active_source_sha256"] == "1" * 64
        assert state["phase_a_published_postimage_sha256"] == "2" * 64

    def test_phase4_completion_requires_both_inventory_digests(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase4-document",
        )
        prepared = _prepare_completion(
            tmp_path,
            store,
            effect_plan=(),
            from_phase="phase4-document",
            to_phase="DONE",
        )
        _commit_routed_completion(store, prepared)
        before = store.load()

        with pytest.raises(StateAdvanceError) as raised:
            store.complete_controller_completion(prepared)

        assert raised.value.validator == "completion_binding"
        assert store.load() == before

    def test_controller_completion_failure_uses_exact_raw_marker_cas(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        malformed = {"schema_version": 1, "completion_id": None}
        state = store.load()
        state[PENDING_CONTROLLER_COMPLETION_KEY] = malformed
        state["controller_completion_failure"] = {"raw": "corrupt"}
        store.save(state)

        store.record_controller_completion_failure(
            malformed,
            "intent_invalid",
        )

        failed = store.load()
        assert failed[PENDING_CONTROLLER_COMPLETION_KEY] == malformed
        assert failed["status"] == "blocked"
        assert failed["blocked_reason"] == "controller_completion_pending"
        assert failed["controller_completion_failure"] == {
            "schema_version": 1,
            "code": "intent_invalid",
            "resume_status": "running",
            "resume_blocked_reason": None,
        }
        before = store.load()
        with pytest.raises(StateAdvanceError):
            store.record_controller_completion_failure(
                None,
                "intent_invalid",
            )
        assert store.load() == before

    def test_controller_completion_failure_preserves_lifecycle_until_final(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        state = store.load()
        state["status"] = "blocked"
        state["blocked_reason"] = "needs_judgment"
        store.save(state)
        prepared = _prepare_completion(
            tmp_path,
            store,
            effect_plan=(),
        )
        _commit_routed_completion(store, prepared)

        store.record_controller_completion_failure(
            prepared.marker.to_dict(),
            "stage_io",
        )
        first = store.load()["controller_completion_failure"]
        store.record_controller_completion_failure(
            prepared.marker.to_dict(),
            "stage_missing",
        )

        failed = store.load()
        assert failed["controller_completion_failure"] == {
            **first,
            "code": "stage_missing",
        }
        store.complete_controller_completion(prepared)
        completed = store.load()
        assert completed["status"] == "blocked"
        assert completed["blocked_reason"] == "needs_judgment"
        assert "controller_completion_failure" not in completed

    def test_nested_publication_and_completion_failures_restore_once(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        prepared = _prepare_completion(
            tmp_path,
            store,
            external_publication=True,
            effect_plan=(),
        )
        _commit_routed_completion(store, prepared)
        store.record_external_publication_failure(
            VALID_MARKER,
            "stage_missing",
        )
        store.record_controller_completion_failure(
            prepared.marker.to_dict(),
            "intent_invalid",
        )

        nested = store.load()
        assert nested["controller_completion_failure"] == {
            "schema_version": 1,
            "code": "intent_invalid",
            "resume_status": "running",
            "resume_blocked_reason": None,
        }
        store.handoff_external_publication(VALID_MARKER, prepared)
        handed_off = store.load()
        assert handed_off["status"] == "blocked"
        assert handed_off["blocked_reason"] == (
            "controller_completion_pending"
        )
        next_prepared = load_prepared_controller_completion(
            tmp_path,
            store.squad_dir,
            handed_off[PENDING_CONTROLLER_COMPLETION_KEY],
        )
        store.complete_controller_completion(next_prepared)
        completed = store.load()
        assert completed["status"] == "running"
        assert "blocked_reason" not in completed

    def test_completion_missing_failure_requires_publication_authority(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        state = store.load()
        state[PENDING_EXTERNAL_PUBLICATION_KEY] = VALID_MARKER
        store.save(state)

        store.record_controller_completion_failure(
            None,
            "completion_missing",
        )

        failed = store.load()
        assert failed[PENDING_EXTERNAL_PUBLICATION_KEY] == VALID_MARKER
        assert failed["controller_completion_failure"]["code"] == (
            "completion_missing"
        )
        state = store.load()
        state.pop(PENDING_EXTERNAL_PUBLICATION_KEY)
        store.save(state)
        before = store.load()
        with pytest.raises(StateAdvanceError):
            store.record_controller_completion_failure(
                None,
                "completion_missing",
            )
        assert store.load() == before

    @pytest.mark.parametrize(
        "tampering",
        [
            "intent",
            "marker",
            "receipts",
            "future_receipts",
            "oversized_receipts",
            "malformed_state_marker",
            "state_marker_mismatch",
            "dispatch_id",
            "dispatch_judgments",
        ],
    )
    def test_controller_completion_tampering_writes_nothing(
        self,
        tmp_path,
        tampering,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        prepared = _prepare_completion(tmp_path, store)
        _commit_routed_completion(store, prepared)
        action = lambda: store.advance_controller_completion(prepared)
        if tampering == "intent":
            prepared = replace(
                prepared,
                intent=replace(
                    prepared.intent,
                    context_reason="forged",
                ),
            )
            action = lambda: store.advance_controller_completion(prepared)
        elif tampering == "marker":
            prepared = replace(
                prepared,
                marker=replace(
                    prepared.marker,
                    receipts_sha256="0" * 64,
                ),
            )
            action = lambda: store.advance_controller_completion(prepared)
        elif tampering == "receipts":
            prepared = replace(
                prepared,
                _receipts_json=b'{"raw":"corrupt"}',
            )
            action = lambda: store.advance_controller_completion(prepared)
        elif tampering == "future_receipts":
            prepared = replace(
                prepared,
                _receipts_json=json.dumps(
                    {
                        "schema_version": 1,
                        "completion_id": prepared.marker.completion_id,
                        "effects": {
                            "journal": {"schema_version": 1},
                            "timing": {"schema_version": 1},
                        },
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            action = lambda: store.advance_controller_completion(prepared)
        elif tampering == "oversized_receipts":
            prepared = replace(
                prepared,
                _receipts_json=json.dumps(
                    {
                        "schema_version": 1,
                        "completion_id": prepared.marker.completion_id,
                        "effects": {
                            "journal": {
                                "padding": "x" * 1_048_576,
                            },
                        },
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            action = lambda: store.advance_controller_completion(prepared)
        elif tampering in {
            "malformed_state_marker",
            "state_marker_mismatch",
        }:
            one_ahead = _rewrite_completion_receipts(
                tmp_path,
                store,
                prepared,
                {"journal": {"schema_version": 1}},
            )
            state = store.load()
            state[PENDING_CONTROLLER_COMPLETION_KEY] = (
                None
                if tampering == "malformed_state_marker"
                else {
                    **prepared.marker.to_dict(),
                    "receipts_sha256": "1" * 64,
                }
            )
            store.save(state)
            action = lambda: store.advance_controller_completion(
                one_ahead
            )
        elif tampering == "dispatch_id":
            state = store.load()
            state["last_dispatch"]["dispatch_id"] = "1" * 32
            store.save(state)
            one_ahead = _rewrite_completion_receipts(
                tmp_path,
                store,
                prepared,
                {"journal": {"schema_version": 1}},
            )
            action = lambda: store.advance_controller_completion(
                one_ahead
            )
        else:
            state = store.load()
            state["last_dispatch"]["judgment_payload_sha256"] = [
                "0" * 64
            ]
            store.save(state)
            one_ahead = _rewrite_completion_receipts(
                tmp_path,
                store,
                prepared,
                {"journal": {"schema_version": 1}},
            )
            action = lambda: store.advance_controller_completion(
                one_ahead
            )
        before = store.load()

        with pytest.raises(StateAdvanceError):
            action()

        assert store.load() == before

    @pytest.mark.parametrize(
        ("method_name", "save_then_raise"),
        [
            ("handoff", False),
            ("handoff", True),
            ("advance", False),
            ("advance", True),
            ("record", False),
            ("record", True),
            ("complete", False),
            ("complete", True),
        ],
    )
    def test_controller_completion_state_save_ambiguity(
        self,
        tmp_path,
        method_name,
        save_then_raise,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        if method_name == "handoff":
            prepared = _prepare_completion(
                tmp_path,
                store,
                external_publication=True,
            )
            _commit_routed_completion(store, prepared)
            operation = lambda: store.handoff_external_publication(
                VALID_MARKER,
                prepared,
            )
        elif method_name == "advance":
            original = _prepare_completion(tmp_path, store)
            _commit_routed_completion(store, original)
            prepared = _rewrite_completion_receipts(
                tmp_path,
                store,
                original,
                {"journal": {"schema_version": 1}},
            )
            operation = lambda: store.advance_controller_completion(
                prepared
            )
        elif method_name == "record":
            prepared = _prepare_completion(tmp_path, store)
            _commit_routed_completion(store, prepared)
            operation = lambda: store.record_controller_completion_failure(
                prepared.marker.to_dict(),
                "stage_io",
            )
        else:
            prepared = _prepare_completion(
                tmp_path,
                store,
                effect_plan=(),
            )
            _commit_routed_completion(store, prepared)
            operation = lambda: store.complete_controller_completion(
                prepared
            )
        before = store.load()
        original_save = store._save_unlocked

        def injected_save(state):
            if save_then_raise:
                original_save(state)
            raise OSError("injected save ambiguity")

        with patch.object(store, "_save_unlocked", side_effect=injected_save):
            if save_then_raise:
                operation()
            else:
                with pytest.raises(StateAdvanceError):
                    operation()

        after = store.load()
        if not save_then_raise:
            assert after == before
        elif method_name == "handoff":
            assert PENDING_EXTERNAL_PUBLICATION_KEY not in after
            assert after[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == (
                "journal"
            )
        elif method_name == "advance":
            assert after[PENDING_CONTROLLER_COMPLETION_KEY]["step"] == (
                "timing"
            )
        elif method_name == "record":
            assert after["controller_completion_failure"]["code"] == (
                "stage_io"
            )
        else:
            assert PENDING_CONTROLLER_COMPLETION_KEY not in after
            assert after["last_dispatch"]["post_dispatch_complete"] is True

    def test_routed_advance_accepts_only_exact_saved_then_raised_state(
        self,
        tmp_path,
    ) -> None:
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        prepared_completion = _prepare_completion(
            tmp_path,
            store,
            external_publication=True,
            effect_plan=(),
        )
        original_save = store._save_unlocked

        def save_then_raise(state):
            original_save(state)
            raise OSError("injected route save ambiguity")

        with patch.object(
            store,
            "_save_unlocked",
            side_effect=save_then_raise,
        ):
            receipt = _advance(
                store,
                "init",
                "next",
                _result("DONE", phase_id="init"),
                token_usage_delta=17,
                dispatch_id=(
                    prepared_completion.marker.completion_id
                ),
                transaction_state_updates={
                    PENDING_CONTROLLER_COMPLETION_KEY: (
                        prepared_completion.marker.to_dict()
                    ),
                    PENDING_EXTERNAL_PUBLICATION_KEY: VALID_MARKER,
                },
            )

        state = store.load()
        assert receipt.dispatch_id == (
            prepared_completion.marker.completion_id
        )
        assert state["token_usage"] == 17
        assert state["last_dispatch"]["dispatch_id"] == receipt.dispatch_id
        assert state["last_dispatch"]["post_dispatch_complete"] is False
        assert state[PENDING_CONTROLLER_COMPLETION_KEY] == (
            prepared_completion.marker.to_dict()
        )
        assert state[PENDING_EXTERNAL_PUBLICATION_KEY] == VALID_MARKER

    def test_advance_records_completed_phase_provenance(self, tmp_path):
        store = _store(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase1-constitution",
        )
        _advance(
            store,
            "phase1-constitution",
            "phase1-what",
            _result("DONE", phase_id="phase1-constitution"),
        )

        assert store.load()["completed_phases"] == ["phase1-constitution"]

    def test_advance_applies_state_updates(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        _advance(
            store,
            "init",
            "phase1-discover",
            _result("DONE", {"coverage_pct": 72}),
        )
        assert store.load()["coverage_pct"] == 72

    def test_provider_cannot_report_bootstrapped_full_spec_identity(self, tmp_path):
        """Phase A identity can be changed only through trusted store effects."""
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "phase1-what")
        state = store.load()
        state.update(
            {
                "spec_id": "005-opta-search-shows-stats",
                "spec_dir": "runs/r/specs/005-opta-search-shows-stats",
                "published_spec_dir": "specs/005-opta-search-shows-stats",
                "feature_branch": "005-opta-search-shows-stats",
                "specify_feature_directory": "runs/r/specs/005-opta-search-shows-stats",
            }
        )
        store.save(state)

        before = store.load()
        with pytest.raises(ControllerStateContractViolation):
            _result(
                "DONE",
                {"spec_id": "005", "spec_dir": "specs/005-opta-search-shows-stats"},
                phase_id="phase1-what",
            )
        assert store.load() == before

    def test_invalid_advance_raises_without_success_state_mutation(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        before = store.load()
        invalid = replace(
            _result("DONE", {"coverage_pct": 72}),
            provider_update_keys=frozenset(),
        )

        with patch.object(store, "save", wraps=store.save) as save:
            with pytest.raises(RuntimeError) as raised:
                _advance(
                    store,
                    "init",
                    "phase1-discover",
                    invalid,
                )

        after = store.load()
        assert raised.type.__name__ == "StateAdvanceError"
        assert save.call_count == 0
        assert after["status"] == before["status"]
        assert after["phase"] == before["phase"]
        assert after["completed_phases"] == before["completed_phases"]
        assert after["last_dispatch"] == before["last_dispatch"]
        assert "coverage_pct" not in after

    def test_advance_rejects_raw_result_without_compatibility_fallback(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        before = store.load()

        with pytest.raises(RuntimeError) as raised:
            store.advance("init", "phase1-discover", _raw_result())

        assert raised.type.__name__ == "StateAdvanceError"
        assert store.load() == before

    @pytest.mark.parametrize(
        "tampered",
        [
            lambda prepared: replace(
                prepared,
                controller_contract_sha256=None,
            ),
            lambda prepared: replace(
                prepared,
                controller_update_keys=frozenset(),
            ),
        ],
        ids=["missing-contract-digest", "ownership-key-mismatch"],
    )
    def test_advance_rejects_tampered_prepared_receipt_without_write(
        self,
        tmp_path,
        tampered,
    ):
        store = _store(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase3-tasks-lexicon",
        )
        before = store.load()

        with patch.object(store, "save", wraps=store.save) as save:
            with pytest.raises(RuntimeError) as raised:
                _advance(
                    store,
                    "phase3-tasks-lexicon",
                    "phase3-understanding",
                    tampered(_tasks_result()),
                )

        assert raised.type.__name__ == "StateAdvanceError"
        assert save.call_count == 0
        assert store.load() == before

    @pytest.mark.parametrize("tamper_mode", ["mutate", "replace"])
    def test_advance_rejects_schema_valid_private_result_tampering(
        self,
        tmp_path,
        tamper_mode,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        before = store.load()
        prepared = _result("DONE", {"coverage_pct": 72})
        if tamper_mode == "mutate":
            prepared._result.echelon_result["state_updates"]["coverage_pct"] = 73
        else:
            object.__setattr__(
                prepared,
                "_result",
                _raw_result("DONE", {"coverage_pct": 73}),
            )

        with patch.object(store, "save", wraps=store.save) as save:
            with pytest.raises(StateAdvanceError):
                _advance(
                    store,
                    "init",
                    "phase1-discover",
                    prepared,
                )

        assert save.call_count == 0
        assert store.load() == before

    @pytest.mark.parametrize(
        "tamper",
        [
            lambda prepared: replace(
                prepared,
                controller_contract_name="forged_valid_name",
                controller_contract_sha256="a" * 64,
            ),
            lambda prepared: replace(
                prepared,
                provider_update_keys=prepared.controller_update_keys,
                controller_update_keys=frozenset(),
            ),
            lambda prepared: replace(
                prepared,
                normalized_paths=(
                    "$.state_updates.tasks_lexicon_report",
                ),
            ),
            lambda prepared: replace(
                prepared,
                routing_override="phase3-understanding",
            ),
        ],
        ids=[
            "valid-looking-contract-pair",
            "provider-controller-reclassification",
            "normalized-paths",
            "routing-override",
        ],
    )
    def test_advance_rejects_outer_metadata_forgery_against_attestation(
        self,
        tmp_path,
        tamper,
    ):
        store = _store(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase3-tasks-lexicon",
        )
        before = store.load()

        with patch.object(store, "save", wraps=store.save) as save:
            with pytest.raises(StateAdvanceError):
                _advance(
                    store,
                    "phase3-tasks-lexicon",
                    "phase3-understanding",
                    tamper(_tasks_result()),
                )

        assert save.call_count == 0
        assert store.load() == before

    def test_attested_routing_override_must_match_requested_destination(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        before = store.load()
        prepared = _result(
            "DONE",
            phase_id="init",
            routing_override="phase1-discover",
        )

        with patch.object(store, "save", wraps=store.save) as save:
            with pytest.raises(StateAdvanceError):
                _advance(store, "init", "phase1-what", prepared)

        assert save.call_count == 0
        assert store.load() == before

    def test_advance_applies_iteration_and_contract_receipt_atomically(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize(
            "r",
            "greenfield",
            "msg",
            0,
            "phase3-tasks-lexicon",
        )
        state = store.load()
        state["controller_contract_error"] = {"prior": "diagnostic"}
        store.save(state)
        prepared = _tasks_result(report=PurePath("tasks-lexicon-report.json"))

        with patch.object(
            store,
            "_save_unlocked",
            wraps=store._save_unlocked,
        ) as save:
            receipt = _advance(
                store,
                "phase3-tasks-lexicon",
                "phase3-understanding",
                prepared,
                increment_iteration=True,
            )

        state = store.load()
        assert save.call_count == 1
        assert state["phase"] == "phase3-understanding"
        assert state["iteration"] == 1
        assert state["last_dispatch"]["controller_contract"] == "tasks_lexicon"
        assert (
            state["last_dispatch"]["controller_contract_sha256"]
            == prepared.controller_contract_sha256
        )
        assert state["last_dispatch"]["controller_normalized"] is True
        assert state["last_dispatch"]["controller_normalized_paths"] == [
            "$.state_updates.tasks_lexicon_report"
        ]
        assert "tasks-lexicon-report.json" not in str(state["last_dispatch"])
        assert "controller_contract_error" not in state
        assert receipt.from_phase == "phase3-tasks-lexicon"
        assert receipt.to_phase == "phase3-understanding"
        assert receipt.controller_contract == "tasks_lexicon"
        assert (
            receipt.controller_contract_sha256
            == prepared.controller_contract_sha256
        )

    def test_advance_applies_sealed_removals_and_terminal_control_in_one_save(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "gate")
        state = store.load()
        state.update(
            {
                "stale_evidence": "remove-me",
                "lexicon_warning_waiver": True,
            }
        )
        store.save(state)
        prepared = prepare_phase_result(
            PhaseNode(
                id="gate",
                type="agent",
                allowed_state_updates=["fresh_evidence"],
            ),
            _raw_result("DONE", {"fresh_evidence": True}),
            controller_updates={},
            state_removals={
                "stale_evidence",
                "lexicon_warning_waiver",
            },
            control_updates={
                "status": "blocked",
                "blocked_reason": "lexicon_gate_exhausted",
                "lexicon_gate_exhausted": True,
            },
        )

        with patch.object(
            store,
            "_save_unlocked",
            wraps=store._save_unlocked,
        ) as save:
            _advance(store, "gate", "terminal-blocked", prepared)

        committed = store.load()
        assert save.call_count == 1
        assert committed["phase"] == "terminal-blocked"
        assert committed["status"] == "blocked"
        assert committed["blocked_reason"] == "lexicon_gate_exhausted"
        assert committed["lexicon_gate_exhausted"] is True
        assert committed["fresh_evidence"] is True
        assert "stale_evidence" not in committed
        assert "lexicon_warning_waiver" not in committed

    def test_explicit_iteration_update_wins_over_selected_increment(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "phase3-plan")

        _advance(
            store,
            "phase3-plan",
            "phase3-tasks-lexicon",
            _result("DONE", {}, phase_id="phase3-plan"),
            increment_iteration=True,
            transaction_state_updates={"iteration": 7},
        )

        assert store.load()["iteration"] == 7

    def test_conditional_skip_identity_is_committed_with_receipt(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "phase1-modeler")

        with patch.object(
            store,
            "_save_unlocked",
            wraps=store._save_unlocked,
        ) as save:
            receipt = _advance(
                store,
                "phase1-modeler",
                "phase1-tracker",
                _result("DONE", phase_id="phase1-modeler"),
                conditional_skip=True,
            )

        state = store.load()
        assert save.call_count == 1
        assert state["last_dispatch"]["conditional_skip"] is True
        assert "manual_phase_run" not in state["last_dispatch"]
        assert receipt.conditional_skip is True

    def test_versioned_run_records_idempotent_completion_outcomes(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "phase1-modeler")
        state = store.load()
        state["checkpoint_policy_version"] = 2
        state["phase_completion_outcomes"] = []
        store.save(state)

        first = _prepare_completion(
            tmp_path,
            store,
            completion_id="a" * 32,
            effect_plan=(),
            from_phase="phase1-modeler",
            to_phase="phase1-modeler",
        )
        original_save = store._save_unlocked

        def save_then_raise(next_state):
            original_save(next_state)
            raise OSError("injected route save ambiguity")

        with patch.object(store, "_save_unlocked", side_effect=save_then_raise):
            _advance(
                store,
                "phase1-modeler",
                "phase1-modeler",
                _result("DONE", phase_id="phase1-modeler"),
                conditional_skip=True,
                checkpoint_policy="required",
                dispatch_id=first.marker.completion_id,
                transaction_state_updates={
                    PENDING_CONTROLLER_COMPLETION_KEY: first.marker.to_dict(),
                },
            )

        second = _prepare_completion(
            tmp_path,
            store,
            completion_id="b" * 32,
            effect_plan=(),
            from_phase="phase1-modeler",
            to_phase="phase1-tracker",
        )
        _advance(
            store,
            "phase1-modeler",
            "phase1-tracker",
            _result("DONE", phase_id="phase1-modeler"),
            checkpoint_policy="required",
            dispatch_id=second.marker.completion_id,
            transaction_state_updates={
                PENDING_CONTROLLER_COMPLETION_KEY: second.marker.to_dict(),
            },
        )

        assert store.load()["phase_completion_outcomes"] == [
            {
                "completion_id": "a" * 32,
                "phase": "phase1-modeler",
                "next_phase": "phase1-modeler",
                "outcome": "skipped",
                "checkpoint": "required",
            },
            {
                "completion_id": "b" * 32,
                "phase": "phase1-modeler",
                "next_phase": "phase1-tracker",
                "outcome": "executed",
                "checkpoint": "required",
            },
        ]

    def test_checkpoint_policy_requires_a_supported_value(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "phase1-modeler")

        with pytest.raises(StateAdvanceError) as raised:
            _advance(
                store,
                "phase1-modeler",
                "phase1-tracker",
                _result("DONE", phase_id="phase1-modeler"),
                checkpoint_policy="sometimes",
            )

        assert raised.value.json_path == "$.checkpoint_policy"

    def test_completion_id_collision_with_different_outcome_is_rejected(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "phase1-modeler")
        state = store.load()
        state["checkpoint_policy_version"] = 2
        state["phase_completion_outcomes"] = [{
            "completion_id": "a" * 32,
            "phase": "phase1-modeler",
            "next_phase": "phase1-tracker",
            "outcome": "executed",
            "checkpoint": "required",
        }]
        store.save(state)
        before = store.load()
        completion = _prepare_completion(
            tmp_path,
            store,
            completion_id="a" * 32,
            effect_plan=(),
            from_phase="phase1-modeler",
            to_phase="phase1-modeler",
        )

        with pytest.raises(StateAdvanceError) as raised:
            _advance(
                store,
                "phase1-modeler",
                "phase1-modeler",
                _result("DONE", phase_id="phase1-modeler"),
                checkpoint_policy="required",
                dispatch_id=completion.marker.completion_id,
                transaction_state_updates={
                    PENDING_CONTROLLER_COMPLETION_KEY: completion.marker.to_dict(),
                },
            )

        assert raised.value.validator == "completion_binding"
        assert store.load() == before

    def test_conditional_skip_identity_requires_a_boolean(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "phase1-modeler")
        before = store.load()

        with patch.object(store, "save", wraps=store.save) as save:
            with pytest.raises(StateAdvanceError) as raised:
                _advance(
                    store,
                    "phase1-modeler",
                    "phase1-tracker",
                    _result("DONE", phase_id="phase1-modeler"),
                    conditional_skip=1,
                )

        assert raised.value.validator == "type"
        assert raised.value.json_path == "$.conditional_skip"
        assert save.call_count == 0
        assert store.load() == before

    def test_self_loop_manual_advance_records_one_successful_receipt(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "phase2-decide")

        receipt = _advance(
            store,
            "phase2-decide",
            "phase2-decide",
            _result("PASS", phase_id="phase2-decide"),
            manual_phase_run=True,
        )

        state = store.load()
        assert state["phase"] == "phase2-decide"
        assert state["completed_phases"] == ["phase2-decide"]
        assert state["last_dispatch"]["manual_phase_run"] is True
        assert state["last_dispatch"]["conditional_skip"] is False
        assert receipt.conditional_skip is False
        assert state["manual_phase_runs"] == [
            {
                "phase_id": "phase2-decide",
                "next_phase": "phase2-decide",
                "verdict": "PASS",
                "completed_at": receipt.completed_at,
            }
        ]

    def test_recovery_decision_applies_effects_without_phase_completion(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "blocked-phase")
        state = store.load()
        state.update(
            {
                "status": "blocked",
                "blocked_reason": "needs_judgment",
                "escalation_question": "Choose",
            }
        )
        store.save(state)
        prepared = prepare_phase_result(
            PhaseNode(
                id="blocked-phase",
                type="agent",
                allowed_state_updates=[],
            ),
            _raw_result("JUDGMENT_RESOLVED", {}),
            controller_updates={},
            state_removals={
                "escalation_question",
            },
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase="blocked-phase"
        )
        decision = store.prepare_routing_decision(
            prepared,
            snapshot=snapshot,
            from_phase="blocked-phase",
            to_phase="resumed-phase",
            transaction_state_updates={
                "status": "running",
                "escalation_resolved": True,
            },
            transaction_state_removals={"blocked_reason"},
            source="commander_recovery",
            record_completion=False,
        )

        store.advance(
            "blocked-phase",
            "resumed-phase",
            decision,
        )

        recovered = store.load()
        assert recovered["phase"] == "resumed-phase"
        assert recovered["status"] == "running"
        assert recovered["escalation_resolved"] is True
        assert "blocked_reason" not in recovered
        assert "escalation_question" not in recovered
        assert recovered["completed_phases"] == []
        assert (
            recovered["last_dispatch"]["routing_source"]
            == "commander_recovery"
        )

    def test_advance_preserves_status_guard_and_phase_a_identity(self, tmp_path, caplog):
        import logging

        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "phase1-what")
        state = store.load()
        state.update(
            {
                "status": "done",
                "spec_id": "005-demo",
                "feature_branch": "005-demo",
            }
        )
        store.save(state)

        with caplog.at_level(logging.WARNING, logger="harness.squad_state"):
            _advance(
                store,
                "phase1-what",
                "phase1-why2",
                _result("DONE", {}, phase_id="phase1-what"),
                transaction_state_updates={"status": "blocked"},
            )

        advanced = store.load()
        assert "Invalid squad status transition" in caplog.text
        assert advanced["status"] == "blocked"
        assert advanced["spec_id"] == "005-demo"

    def test_in_memory_advance_failure_is_typed_and_writes_nothing(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        before = store.load()
        prepared = _result("DONE", {})

        with patch.object(store, "save", wraps=store.save) as save:
            with pytest.raises(RuntimeError) as raised:
                _advance(
                    store,
                    "init",
                    "phase1-discover",
                    prepared,
                    transaction_state_updates={"status": []},
                )

        assert raised.type.__name__ == "StateAdvanceError"
        assert save.call_count == 0
        assert store.load() == before

    def test_cancel_flag(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        assert store.is_cancel_requested() is False
        store.set_cancel_requested()
        assert store.is_cancel_requested() is True

    def test_token_tracking(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 100_000, "init")
        store.increment_token_usage(10_000)
        store.increment_token_usage(5_000)
        assert store.token_usage() == 15_000

    def test_atomic_write_no_partial_state(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        tmp_file = (tmp_path / "squad/run-test/state.json").with_suffix(".json.tmp")
        assert not tmp_file.exists()

    def test_set_blocked(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        store.set_blocked("understanding unavailable")
        state = store.load()
        assert state["status"] == "blocked"
        assert state["blocked_reason"] == "understanding unavailable"

    def test_save_persists_typed_blocked_decision_for_escalation(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "phase1-why1")
        state = store.load()
        state.update(
            {
                "status": "blocked",
                "blocked_reason": "consecutive_why_fails",
                "escalation_question": "What constraint should CARTOGRAPHER apply?",
            }
        )

        store.save(state)

        reloaded = SquadStateStore(tmp_path / "squad/run-test").load()
        assert reloaded["blocked_decision"]["answer_type"] == "free_text"
        assert reloaded["blocked_decision"]["question"] == (
            "What constraint should CARTOGRAPHER apply?"
        )
        assert reloaded["blocked_decision"]["blocked_phase"] == "phase1-why1"
        assert reloaded["blocked_decision"]["blocked_reason"] == "consecutive_why_fails"

    def test_save_persists_choice_blocked_decision_for_escalation_options(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "checkpoint-assess")
        state = store.load()
        state.update(
            {
                "status": "blocked",
                "blocked_reason": "human_gate",
                "escalation_question": "A: return\nB: proceed",
                "escalation_options": [
                    {
                        "id": "return_to_what",
                        "label": "Return to WHAT",
                        "next_phase": "phase1-what",
                        "recommended": True,
                    },
                    {
                        "id": "proceed",
                        "label": "Proceed",
                        "next_phase": "phase2-decide",
                    },
                ],
            }
        )

        store.save(state)

        decision = SquadStateStore(tmp_path / "squad/run-test").load()["blocked_decision"]
        assert decision["answer_type"] == "choice"
        assert decision["recommended_answer"] == "return_to_what"
        assert decision["options"][0]["id"] == "return_to_what"


def test_store_creates_squad_and_staging_dirs(tmp_path):
    from harness.squad_state import SquadStateStore
    squad_dir = tmp_path / "squad" / "run-test"
    store = SquadStateStore(squad_dir)
    assert (squad_dir).exists()
    assert (squad_dir / "staging").exists()


def test_state_path_is_inside_squad_dir(tmp_path):
    from harness.squad_state import SquadStateStore
    squad_dir = tmp_path / "squad" / "run-test"
    store = SquadStateStore(squad_dir)
    store.initialize("r1", "semi", "msg", 0, "init")
    assert (squad_dir / "state.json").exists()


def test_initialize_writes_squad_and_staging_paths(tmp_path):
    from harness.squad_state import SquadStateStore
    squad_dir = tmp_path / "squad" / "run-test"
    store = SquadStateStore(squad_dir)
    store.initialize("r1", "semi", "msg", 0, "init")
    state = store.load()
    assert state["squad_dir"] == str(squad_dir)
    assert state["staging_dir"] == str(squad_dir / "staging")


def test_squad_dir_property(tmp_path):
    from harness.squad_state import SquadStateStore
    squad_dir = tmp_path / "squad" / "run-test"
    store = SquadStateStore(squad_dir)
    assert store.squad_dir == squad_dir


def test_staging_dir_property(tmp_path):
    from harness.squad_state import SquadStateStore
    squad_dir = tmp_path / "squad" / "run-test"
    store = SquadStateStore(squad_dir)
    assert store.staging_dir == squad_dir / "staging"


def test_initialize_sets_why_fail_count_zero(tmp_path):
    from harness.squad_state import SquadStateStore
    store = SquadStateStore(tmp_path / "squad/run-test")
    store.initialize("r1", "semi", "msg", 0, "init")
    assert store.load()["why_fail_count"] == 0


def test_increment_why_fail_count(tmp_path):
    from harness.squad_state import SquadStateStore
    store = SquadStateStore(tmp_path / "squad/run-test")
    store.initialize("r1", "semi", "msg", 0, "init")
    store.increment_why_fail_count()
    assert store.load()["why_fail_count"] == 1
    store.increment_why_fail_count()
    assert store.load()["why_fail_count"] == 2


def test_reset_why_fail_count(tmp_path):
    from harness.squad_state import SquadStateStore
    store = SquadStateStore(tmp_path / "squad/run-test")
    store.initialize("r1", "semi", "msg", 0, "init")
    store.increment_why_fail_count()
    store.increment_why_fail_count()
    store.reset_why_fail_count()
    assert store.load()["why_fail_count"] == 0


def test_increment_why_fail_count_returns_new_count(tmp_path):
    from harness.squad_state import SquadStateStore
    store = SquadStateStore(tmp_path / "squad/run-test")
    store.initialize("r1", "semi", "msg", 0, "init")
    assert store.increment_why_fail_count() == 1
    assert store.increment_why_fail_count() == 2


# ── Step 1: fsync ────────────────────────────────────────────────────────────

class TestFsync:
    def test_fsync_called_on_save(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        real_fsync = os.fsync
        synchronized_types = []

        def observed_fsync(descriptor):
            synchronized_types.append(os.fstat(descriptor).st_mode)
            real_fsync(descriptor)

        with patch(
            "harness.squad_state.os.fsync",
            side_effect=observed_fsync,
        ):
            store.save(store.load())
        assert any(stat.S_ISREG(mode) for mode in synchronized_types)
        assert any(stat.S_ISDIR(mode) for mode in synchronized_types)

    def test_state_save_fsyncs_file_then_replaces_then_fsyncs_parent(
        self,
        tmp_path,
    ):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        calls = []
        real_fsync = os.fsync
        real_replace = os.replace

        def observed_fsync(descriptor):
            mode = os.fstat(descriptor).st_mode
            calls.append(
                "dir_fsync" if stat.S_ISDIR(mode) else "file_fsync"
            )
            real_fsync(descriptor)

        def observed_replace(source, target, *args, **kwargs):
            calls.append("replace")
            return real_replace(source, target, *args, **kwargs)

        with (
            patch(
                "harness.squad_state.os.fsync",
                side_effect=observed_fsync,
            ),
            patch(
                "harness.squad_state.os.replace",
                side_effect=observed_replace,
            ),
        ):
            store.save(store.load())

        assert calls[-3:] == ["file_fsync", "replace", "dir_fsync"]

    def test_initial_state_create_fsyncs_file_and_parent(
        self,
        tmp_path,
    ):
        store = SquadStateStore(tmp_path / "squad/run-test")
        synchronized_types = []
        real_fsync = os.fsync

        def observed_fsync(descriptor):
            synchronized_types.append(os.fstat(descriptor).st_mode)
            real_fsync(descriptor)

        with patch(
            "harness.squad_state.os.fsync",
            side_effect=observed_fsync,
        ):
            store.initialize("r1", "semi", "msg", 0, "init")

        assert stat.S_ISREG(synchronized_types[-2])
        assert stat.S_ISDIR(synchronized_types[-1])

    def test_directory_creation_is_durable(self, tmp_path):
        synchronized = []
        real_fsync = os.fsync

        def observed_fsync(descriptor):
            metadata = os.fstat(descriptor)
            if stat.S_ISDIR(metadata.st_mode):
                synchronized.append((metadata.st_dev, metadata.st_ino))
            real_fsync(descriptor)

        squad_dir = tmp_path / "runs" / "spec-1" / "squad"
        with patch(
            "harness.squad_state.os.fsync",
            side_effect=observed_fsync,
        ):
            SquadStateStore(squad_dir)

        squad_identity = squad_dir.stat()
        staging_identity = (squad_dir / "staging").stat()
        assert (
            squad_identity.st_dev,
            squad_identity.st_ino,
        ) in synchronized
        assert (
            staging_identity.st_dev,
            staging_identity.st_ino,
        ) in synchronized

    def test_fsync_retries_eintr(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        real_fsync = os.fsync
        attempts = 0

        def interrupted_once(descriptor):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError(errno.EINTR, "interrupted")
            real_fsync(descriptor)

        with patch(
            "harness.squad_state.os.fsync",
            side_effect=interrupted_once,
        ):
            store.save(store.load())

        assert attempts >= 3

    def test_directory_creation_parent_failure_is_reconfirmed_on_retry(
        self,
        tmp_path,
    ):
        squad_dir = tmp_path / "runs" / "spec-1" / "squad"
        failed = False
        real_fsync = os.fsync

        def fail_squad_parent_once(descriptor):
            nonlocal failed
            metadata = os.fstat(descriptor)
            if (
                not failed
                and stat.S_ISDIR(metadata.st_mode)
                and squad_dir.is_dir()
                and squad_dir.parent.is_dir()
            ):
                parent = squad_dir.parent.stat()
                if (
                    metadata.st_dev,
                    metadata.st_ino,
                ) == (parent.st_dev, parent.st_ino):
                    failed = True
                    raise OSError(
                        errno.EIO,
                        "injected directory parent sync failure",
                    )
            real_fsync(descriptor)

        with (
            patch(
                "harness.squad_state.os.fsync",
                side_effect=fail_squad_parent_once,
            ),
            pytest.raises(StateDurabilityError) as raised,
        ):
            SquadStateStore(squad_dir)

        assert raised.value.stage == "directory_create"
        assert squad_dir.is_dir()

        synchronized = []

        def observed_fsync(descriptor):
            metadata = os.fstat(descriptor)
            if stat.S_ISDIR(metadata.st_mode):
                synchronized.append((metadata.st_dev, metadata.st_ino))
            real_fsync(descriptor)

        with patch(
            "harness.squad_state.os.fsync",
            side_effect=observed_fsync,
        ):
            store = SquadStateStore(squad_dir)
            store.initialize("r1", "greenfield", "msg", 0, "init")

        parent = squad_dir.parent.stat()
        assert (parent.st_dev, parent.st_ino) in synchronized


class TestDurableStateAuthority:
    @pytest.mark.parametrize("kind", ("symlink", "directory"))
    def test_state_lock_rejects_non_regular_path(
        self,
        tmp_path,
        kind,
    ):
        store = _store(tmp_path)
        lock_path = store.squad_dir / "state.lock"
        if kind == "symlink":
            target = tmp_path / "redirected.lock"
            target.write_bytes(b"")
            lock_path.symlink_to(target)
        else:
            lock_path.mkdir()

        with pytest.raises(StateDurabilityError):
            store.initialize("r1", "greenfield", "msg", 0, "init")

    def test_state_lock_rejects_inode_swap_before_acquisition(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        lock_path = store.squad_dir / "state.lock"
        real_flock = fcntl.flock
        swapped = False

        def swap_named_lock(descriptor, operation):
            nonlocal swapped
            if (
                operation == fcntl.LOCK_EX
                and stat.S_ISREG(os.fstat(descriptor).st_mode)
                and not swapped
            ):
                swapped = True
                old = store.squad_dir / ".old-state-lock"
                os.replace(lock_path, old)
                lock_path.write_bytes(b"")
            return real_flock(descriptor, operation)

        with (
            patch(
                "harness.squad_state.fcntl.flock",
                side_effect=swap_named_lock,
            ),
            pytest.raises(StateDurabilityError),
        ):
            store.save(store.load())

        fresh = SquadStateStore(store.squad_dir)
        fresh.save(fresh.load())

    def test_state_lock_inode_swap_cannot_admit_second_writer(
        self,
        tmp_path,
    ):
        first = _store(tmp_path)
        first.initialize("r1", "greenfield", "msg", 0, "init")
        second = SquadStateStore(first.squad_dir)
        lock_path = first.squad_dir / "state.lock"
        first_entered = Event()
        release_first = Event()
        second_entered = Event()
        first_errors: list[BaseException] = []
        second_errors: list[BaseException] = []

        def hold_first() -> None:
            try:
                with first._lock(exclusive=True):
                    first_entered.set()
                    assert release_first.wait(2)
            except BaseException as exc:
                first_errors.append(exc)

        def enter_second() -> None:
            try:
                with second._lock(exclusive=True):
                    second_entered.set()
            except BaseException as exc:
                second_errors.append(exc)

        first_thread = Thread(target=hold_first)
        first_thread.start()
        assert first_entered.wait(2)
        os.replace(
            lock_path,
            first.squad_dir / ".replaced-state-lock",
        )
        lock_path.write_bytes(b"")
        second_thread = Thread(target=enter_second)
        second_thread.start()

        assert not second_entered.wait(0.2)
        release_first.set()
        first_thread.join(2)
        second_thread.join(2)

        assert second_entered.is_set()
        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert len(first_errors) == 1
        assert isinstance(first_errors[0], StateDurabilityError)
        assert second_errors == []

    def test_confirm_durable_state_requires_exact_revision_and_marker(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        expected = store.load()

        assert store.confirm_durable_state(expected) == expected

        drifted = deepcopy(expected)
        drifted["state_revision"] += 1
        with pytest.raises(StateDurabilityError) as raised:
            store.confirm_durable_state(drifted)
        assert raised.value.stage == "confirm"

    def test_confirm_durable_state_fsyncs_file_then_parent(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        calls = []
        real_fsync = os.fsync

        def observed_fsync(descriptor):
            mode = os.fstat(descriptor).st_mode
            calls.append(
                "dir_fsync" if stat.S_ISDIR(mode) else "file_fsync"
            )
            real_fsync(descriptor)

        with patch(
            "harness.squad_state.os.fsync",
            side_effect=observed_fsync,
        ):
            store.confirm_durable_state(store.load())

        assert calls == ["file_fsync", "dir_fsync"]

    def test_post_replace_parent_sync_failure_is_not_adopted(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "DONE")
        prepared = _prepare_completion(
            tmp_path,
            store,
            origin="terminal",
            external_publication=True,
            effect_plan=(),
            from_phase="DONE",
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase="DONE",
        )
        real_fsync = os.fsync

        def fail_parent_sync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError(errno.EIO, "injected parent sync failure")
            real_fsync(descriptor)

        with (
            patch(
                "harness.squad_state.os.fsync",
                side_effect=fail_parent_sync,
            ),
            pytest.raises(StateDurabilityError) as raised,
        ):
            store.begin_terminal_controller_completion(
                prepared,
                snapshot=snapshot,
            )

        assert raised.value.stage == "post_replace"
        assert prepared._transaction_root.is_dir()

    def test_external_marker_post_replace_failure_stays_distinct(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize(
            "r1",
            "greenfield",
            "msg",
            0,
            "phase1-what",
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase="phase1-what",
        )
        real_fsync = os.fsync

        def fail_parent_sync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError(errno.EIO, "injected parent sync failure")
            real_fsync(descriptor)

        with (
            patch(
                "harness.squad_state.os.fsync",
                side_effect=fail_parent_sync,
            ),
            pytest.raises(StateDurabilityError) as raised,
        ):
            store.begin_external_publication(
                VALID_MARKER,
                snapshot=snapshot,
            )

        assert raised.value.stage == "post_replace"

    def test_confirm_durable_state_rejects_symlink(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        expected = store.load()
        state_path = store.squad_dir / "state.json"
        redirected = tmp_path / "redirected-state.json"
        redirected.write_bytes(state_path.read_bytes())
        state_path.unlink()
        state_path.symlink_to(redirected)

        with pytest.raises(StateDurabilityError) as raised:
            store.confirm_durable_state(expected)

        assert raised.value.stage == "confirm"

    def test_confirm_durable_state_rechecks_file_identity(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        expected = store.load()
        state_path = store.squad_dir / "state.json"
        replaced = False
        real_fsync = os.fsync

        def replace_after_file_sync(descriptor):
            nonlocal replaced
            if (
                not replaced
                and stat.S_ISREG(os.fstat(descriptor).st_mode)
            ):
                replaced = True
                temporary = store.squad_dir / ".identity-replacement"
                temporary.write_bytes(state_path.read_bytes())
                os.replace(temporary, state_path)
            real_fsync(descriptor)

        with (
            patch(
                "harness.squad_state.os.fsync",
                side_effect=replace_after_file_sync,
            ),
            pytest.raises(StateDurabilityError) as raised,
        ):
            store.confirm_durable_state(expected)

        assert raised.value.stage == "confirm"

    def test_true_save_then_raise_adoption_uses_exact_confirmation(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "DONE")
        prepared = _prepare_completion(
            tmp_path,
            store,
            origin="terminal",
            external_publication=True,
            effect_plan=(),
            from_phase="DONE",
        )
        snapshot = store.capture_routing_snapshot(
            expected_phase="DONE",
        )
        original_save = store._save_unlocked
        original_confirm = store._confirm_durable_state_unlocked

        def save_then_raise(state):
            original_save(state)
            raise OSError("injected outer ambiguity")

        with (
            patch.object(
                store,
                "_save_unlocked",
                side_effect=save_then_raise,
            ),
            patch.object(
                store,
                "_confirm_durable_state_unlocked",
                wraps=original_confirm,
            ) as confirm,
        ):
            store.begin_terminal_controller_completion(
                prepared,
                snapshot=snapshot,
            )

        assert confirm.call_count == 1
        assert store.load()[PENDING_CONTROLLER_COMPLETION_KEY] == (
            prepared.marker.to_dict()
        )

    def test_no_stale_tmp_file_after_save(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        state_dir = tmp_path / "squad/run-test"
        leftovers = list(state_dir.glob(".state-*.tmp"))
        assert leftovers == [], f"Stale tmp files: {leftovers}"

    def test_tmp_file_cleaned_up_on_write_error(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        state_dir = tmp_path / "squad/run-test"

        with patch("harness.squad_state.os.fsync", side_effect=OSError("disk full")):
            try:
                store.save(store.load())
            except OSError:
                pass

        leftovers = list(state_dir.glob(".state-*.tmp"))
        assert leftovers == [], f"Tmp file not cleaned up: {leftovers}"


# ── Step 2: .bak ─────────────────────────────────────────────────────────────

class TestBak:
    def test_no_bak_after_first_save(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        bak = tmp_path / "squad/run-test/state.json.bak"
        assert not bak.exists()

    def test_bak_exists_after_second_save(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        store.save(store.load())   # second write
        bak = tmp_path / "squad/run-test/state.json.bak"
        assert bak.exists()

    def test_bak_contains_previous_state(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        state = store.load()
        state["token_usage"] = 1000
        store.save(state)           # writes token_usage=1000; bak = initialized state

        state2 = store.load()
        state2["token_usage"] = 2000
        store.save(state2)          # writes token_usage=2000; bak = token_usage=1000

        import json
        bak_state = json.loads((tmp_path / "squad/run-test/state.json.bak").read_text())
        assert bak_state["token_usage"] == 1000

    def test_bak_write_failure_does_not_abort_save(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")

        with patch("harness.squad_state.Path.write_text", side_effect=OSError("read-only")):
            # save must complete even if .bak write fails
            store.save(store.load())

        assert (tmp_path / "squad/run-test/state.json").exists()


# ── Step 3: status transition model ──────────────────────────────────────────

class TestStatusTransitions:
    def test_valid_transition_running_to_blocked(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        store.set_blocked("reason")
        assert store.load()["status"] == "blocked"

    def test_valid_transition_blocked_to_running(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        store.set_blocked("reason")
        # simulate controller un-blocking by direct save
        state = store.load()
        store._transition_status(state, "running")
        store.save(state)
        assert store.load()["status"] == "running"

    def test_invalid_transition_logs_warning(self, tmp_path, caplog):
        import logging
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        # Attempt running → done directly via state_updates (valid transition)
        state = store.load()
        with caplog.at_level(logging.WARNING, logger="harness.squad_state"):
            store._transition_status(state, "done")
        # running → done IS valid, so no warning
        assert "Invalid squad status transition" not in caplog.text

    def test_invalid_transition_emits_warning_and_still_writes(self, tmp_path, caplog):
        import logging
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        state = store.load()
        with caplog.at_level(logging.WARNING, logger="harness.squad_state"):
            # done is a terminal state; done → blocked is invalid
            state["status"] = "done"
            store._transition_status(state, "blocked")
        assert "Invalid squad status transition" in caplog.text
        assert state["status"] == "blocked"

    def test_trusted_status_effect_routes_through_guard(self, tmp_path, caplog):
        import logging
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        result = _result("DONE", {})
        with caplog.at_level(logging.WARNING, logger="harness.squad_state"):
            _advance(
                store,
                "init",
                "phase1-discover",
                result,
                transaction_state_updates={"status": "done"},
            )
        # running → done is valid, no warning
        assert "Invalid squad status transition" not in caplog.text
        assert store.load()["status"] == "done"


# ── Step 4: token_usage monotonicity ─────────────────────────────────────────

class TestTokenMonotonicity:
    def test_increment_increases_token_usage(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        store.increment_token_usage(100)
        store.increment_token_usage(50)
        assert store.token_usage() == 150

    def test_no_warning_on_normal_increment(self, tmp_path, caplog):
        import logging
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        with caplog.at_level(logging.WARNING, logger="harness.squad_state"):
            store.increment_token_usage(500)
        assert "token_usage decreased" not in caplog.text

    def test_decrease_logs_warning(self, tmp_path, caplog):
        import logging
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 10_000, "init")
        store.increment_token_usage(5_000)
        state = store.load()
        state["token_usage"] = 100  # forced decrease
        with caplog.at_level(logging.WARNING, logger="harness.squad_state"):
            store.save(state)
        assert "token_usage decreased" in caplog.text

    def test_decrease_still_writes_state(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        store.increment_token_usage(5_000)
        state = store.load()
        state["token_usage"] = 100
        store.save(state)
        assert store.token_usage() == 100

    def test_provider_state_updates_cannot_set_token_usage(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        store.increment_token_usage(1_000)
        before = store.load()

        with pytest.raises(ControllerStateContractViolation):
            _result("DONE", {"token_usage": 10})

        assert store.load() == before


# ── Step 5: updated_at on every write ────────────────────────────────────────

class TestUpdatedAt:
    def _ts(self, store) -> str:
        return store.load().get("updated_at", "")

    def test_initialize_sets_updated_at(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        assert self._ts(store) != ""

    def test_set_blocked_updates_timestamp(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        t0 = self._ts(store)
        store.set_blocked("reason")
        assert self._ts(store) >= t0

    def test_set_cancel_requested_updates_timestamp(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        t0 = self._ts(store)
        store.set_cancel_requested()
        assert self._ts(store) >= t0

    def test_increment_token_usage_updates_timestamp(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        t0 = self._ts(store)
        store.increment_token_usage(100)
        assert self._ts(store) >= t0

    def test_increment_why_fail_count_updates_timestamp(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        t0 = self._ts(store)
        store.increment_why_fail_count()
        assert self._ts(store) >= t0

    def test_reset_why_fail_count_updates_timestamp(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        store.increment_why_fail_count()
        t0 = self._ts(store)
        store.reset_why_fail_count()
        assert self._ts(store) >= t0

    def test_advance_updates_timestamp(self, tmp_path):
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        t0 = self._ts(store)
        _advance(store, "init", "phase1-discover", _result())
        assert self._ts(store) >= t0


class TestHumanInputDecisionStateCAS:
    def test_human_input_non_provider_seal_commits_one_v3_pair(self, tmp_path):
        store = _store(tmp_path)
        store.initialize(
            "r1",
            "greenfield",
            "msg",
            0,
            "init",
            autonomy_mode="guided",
        )
        before = store.load()
        request = _human_input_request(
            source_kind="human_gate",
            source_state_revision=before["state_revision"],
        )

        sealed = store.set_human_input_decision(
            request,
            initial_status="awaiting_human",
        )

        assert sealed == store.load()
        assert sealed["state_revision"] == before["state_revision"] + 1
        assert sealed["status"] == "blocked"
        assert sealed["blocked_reason"] == "approval_required"
        assert sealed["escalation_question"] == "May the squad continue?"
        assert [item["id"] for item in sealed["escalation_options"]] == [
            "approve",
            "reject",
        ]
        decision = sealed["blocked_decision"]
        assert decision["schema_version"] == 3
        assert decision["status"] == "awaiting_human"
        assert decision["source_kind"] == "human_gate"
        assert decision["producer_id"] == "init"
        assert decision["source_phase"] == "init"
        assert decision["autonomy_mode"] == "guided"
        assert decision["source_state_revision"] == before["state_revision"]
        assert decision["attempts"] == 0
        assert decision["selected_option_id"] is None
        assert decision["answer_text"] is None
        assert decision["resolved_by"] is None
        assert decision["failure_code"] is None
        assert decision["resolved_at"] is None
        assert decision["recommended_option_id"] == "approve"
        assert decision["recommended_action"] is None
        assert decision["automatic_eligible"] is True
        assert decision["recommendation_rationale"]
        assert decision["recommendation_confidence"] == "medium"
        assert decision["recommendation_authority"] == "provider_evidence"
        assert decision["recommendation_evidence"]
        assert decision["resolution_rationale"] is None
        assert decision["resolution_confidence"] is None
        assert decision["recommendation_followed"] is None
        assert decision["override_reason"] is None
        assert sealed["recovery_instruction"] == {
            "schema_version": 2,
            "kind": "await_human_answer",
            "reason_code": "approval_required",
            "phase": "init",
            "requires_human_input": True,
            "decision_id": decision["id"],
        }

    def test_human_input_non_provider_seal_rejects_stale_existing_and_bad_status(
        self,
        tmp_path,
    ):
        stale_store = SquadStateStore(tmp_path / "stale")
        stale_store.initialize("r1", "greenfield", "msg", 0, "init")
        stale_before = stale_store.load()
        stale_request = _human_input_request(
            source_kind="human_gate",
            source_state_revision=stale_before["state_revision"] - 1,
        )
        with pytest.raises(StateAdvanceError):
            stale_store.set_human_input_decision(
                stale_request,
                initial_status="awaiting_human",
            )
        assert stale_store.load() == stale_before

        active_store = SquadStateStore(tmp_path / "active")
        active_store.initialize("r2", "greenfield", "msg", 0, "init")
        active_request = _human_input_request(
            source_kind="human_gate",
            source_state_revision=active_store.load()["state_revision"],
        )
        active_store.set_human_input_decision(
            active_request,
            initial_status="awaiting_human",
        )
        active_before = active_store.load()
        replacement = _human_input_request(
            source_kind="human_gate",
            source_state_revision=active_before["state_revision"],
        )
        with pytest.raises(StateAdvanceError):
            active_store.set_human_input_decision(
                replacement,
                initial_status="awaiting_human",
            )
        assert active_store.load() == active_before

        invalid_store = SquadStateStore(tmp_path / "invalid")
        invalid_store.initialize("r3", "greenfield", "msg", 0, "init")
        invalid_before = invalid_store.load()
        invalid_request = _human_input_request(
            source_kind="human_gate",
            source_state_revision=invalid_before["state_revision"],
        )
        with pytest.raises(StateAdvanceError):
            invalid_store.set_human_input_decision(
                invalid_request,
                initial_status="resolving",
            )
        assert invalid_store.load() == invalid_before

    @pytest.mark.parametrize(
        ("source_kind", "producer_id", "phase_id"),
        [
            ("provider_escalation", None, "init"),
            ("controller_safeguard", "consecutive_why_fails", "phase1-why2"),
            ("controller_safeguard", "why2_metric_stagnation", "phase1-why2"),
        ],
    )
    def test_human_input_setter_rejects_provider_transaction_sources_without_write(
        self,
        tmp_path,
        source_kind,
        producer_id,
        phase_id,
    ):
        store = SquadStateStore(tmp_path / f"{source_kind}-{producer_id}")
        store.initialize("r1", "greenfield", "msg", 0, phase_id)
        before = store.load()
        request = _human_input_request(
            source_kind=source_kind,
            producer_id=producer_id,
            source_state_revision=before["state_revision"],
            phase_id=phase_id,
        )

        with pytest.raises(StateAdvanceError):
            store.set_human_input_decision(request, initial_status="pending")

        assert store.load() == before

    @pytest.mark.parametrize(
        ("source_kind", "producer_id"),
        [
            ("legacy_recovery", None),
            ("controller_safeguard", "phase_dispatch_limit"),
        ],
    )
    def test_human_input_setter_accepts_non_provider_transaction_sources(
        self,
        tmp_path,
        source_kind,
        producer_id,
    ):
        store = SquadStateStore(tmp_path / f"{source_kind}-{producer_id}")
        store.initialize("r1", "greenfield", "msg", 0, "init")
        before = store.load()
        request = _human_input_request(
            source_kind=source_kind,
            producer_id=producer_id,
            source_state_revision=before["state_revision"],
        )

        sealed = store.set_human_input_decision(
            request,
            initial_status=(
                "pending" if request.automatic_eligible else "awaiting_human"
            ),
        )

        assert sealed == store.load()
        assert sealed["blocked_decision"]["source_kind"] == source_kind
        assert sealed["blocked_decision"]["producer_id"] == (
            producer_id or "init"
        )

    @pytest.mark.parametrize(
        ("source_kind", "producer_id"),
        [
            ("human_gate", None),
            ("legacy_recovery", None),
            ("controller_safeguard", "phase_dispatch_limit"),
        ],
    )
    def test_human_input_advance_rejects_non_provider_transaction_sources_without_write(
        self,
        tmp_path,
        source_kind,
        producer_id,
    ):
        store = SquadStateStore(tmp_path / f"{source_kind}-{producer_id}")
        store.initialize("r1", "greenfield", "msg", 0, "init")
        before = store.load()
        request = _human_input_request(
            source_kind=source_kind,
            producer_id=producer_id,
            source_state_revision=before["state_revision"],
        )

        with pytest.raises(StateAdvanceError):
            _advance(
                store,
                "init",
                "next",
                _result("DONE", {"provider_fact": "attested"}),
                human_input=request,
                human_input_initial_status="pending",
            )

        assert store.load() == before

    def test_human_input_advance_rejects_source_phase_mismatch_without_write(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        before = store.load()
        request = _human_input_request(
            source_kind="provider_escalation",
            source_state_revision=before["state_revision"],
            phase_id="next",
        )

        with pytest.raises(StateAdvanceError):
            _advance(
                store,
                "init",
                "next",
                _result("DONE", {"provider_fact": "attested"}),
                human_input=request,
                human_input_initial_status="pending",
            )

        assert store.load() == before

    @pytest.mark.parametrize(
        ("source_kind", "producer_id", "phase_id", "save_then_raise"),
        [
            ("provider_escalation", None, "init", False),
            ("provider_escalation", None, "init", True),
            (
                "controller_safeguard",
                "consecutive_why_fails",
                "phase1-why2",
                False,
            ),
            (
                "controller_safeguard",
                "consecutive_why_fails",
                "phase1-why2",
                True,
            ),
            (
                "controller_safeguard",
                "why2_metric_stagnation",
                "phase1-why2",
                False,
            ),
            (
                "controller_safeguard",
                "why2_metric_stagnation",
                "phase1-why2",
                True,
            ),
        ],
    )
    def test_human_input_provider_advance_is_preimage_or_complete_v3_postimage(
        self,
        tmp_path,
        source_kind,
        producer_id,
        phase_id,
        save_then_raise,
    ):
        store = SquadStateStore(
            tmp_path / f"{source_kind}-{producer_id}-{save_then_raise}"
        )
        store.initialize(
            "r1",
            "greenfield",
            "msg",
            0,
            phase_id,
            autonomy_mode="banzai",
        )
        before = store.load()
        request = _human_input_request(
            source_kind=source_kind,
            producer_id=producer_id,
            source_state_revision=before["state_revision"],
            phase_id=phase_id,
        )
        snapshot = store.capture_routing_snapshot(expected_phase=phase_id)
        prepared = _result(
            "DONE",
            {"provider_fact": "attested"},
            phase_id=phase_id,
        )
        decision = store.prepare_routing_decision(
            prepared,
            snapshot=snapshot,
            from_phase=phase_id,
            to_phase="next",
            dispatch_id="d" * 32,
        )
        original_save = store._save_unlocked

        def injected_save(state, **kwargs):
            if save_then_raise:
                original_save(state, **kwargs)
            raise OSError("injected human-input save ambiguity")

        initial_status = (
            "pending" if request.automatic_eligible else "awaiting_human"
        )

        with patch.object(
            store,
            "_save_unlocked",
            side_effect=injected_save,
        ):
            if save_then_raise:
                receipt = store.advance(
                    phase_id,
                    "next",
                    decision,
                    human_input=request,
                    human_input_initial_status=initial_status,
                )
            else:
                with pytest.raises(StateAdvanceError):
                    store.advance(
                        phase_id,
                        "next",
                        decision,
                        human_input=request,
                        human_input_initial_status=initial_status,
                    )

        after = store.load()
        if not save_then_raise:
            assert after == before
            return
        assert receipt.state_revision == before["state_revision"] + 1
        assert after["state_revision"] == receipt.state_revision
        assert after["phase"] == "next"
        assert after["provider_fact"] == "attested"
        assert after["last_dispatch"]["dispatch_id"] == "d" * 32
        assert after["last_dispatch"]["state_revision"] == receipt.state_revision
        assert after["blocked_decision"]["schema_version"] == 3
        assert after["blocked_decision"]["source_kind"] == source_kind
        assert after["blocked_decision"]["source_state_revision"] == (
            before["state_revision"]
        )
        assert after["recovery_instruction"]["schema_version"] == 2
        assert after["recovery_instruction"]["decision_id"] == (
            after["blocked_decision"]["id"]
        )

    @pytest.mark.parametrize(
        ("effect_kind", "authority_key"),
        [
            ("update", "blocked_decision"),
            ("update", "recovery_instruction"),
            ("removal", "blocked_decision"),
            ("removal", "recovery_instruction"),
        ],
    )
    def test_human_input_advance_rejects_authority_routing_effects_without_write(
        self,
        tmp_path,
        effect_kind,
        authority_key,
    ):
        store = SquadStateStore(
            tmp_path / f"{effect_kind}-{authority_key}"
        )
        store.initialize("r1", "greenfield", "msg", 0, "init")
        before = store.load()
        request = _human_input_request(
            source_kind="provider_escalation",
            source_state_revision=before["state_revision"],
        )
        transaction_updates = (
            {authority_key: {"masked": True}}
            if effect_kind == "update"
            else None
        )
        transaction_removals = (
            (authority_key,) if effect_kind == "removal" else ()
        )

        with pytest.raises(StateAdvanceError):
            _advance(
                store,
                "init",
                "next",
                _result("DONE", {"provider_fact": "attested"}),
                transaction_state_updates=transaction_updates,
                transaction_state_removals=transaction_removals,
                human_input=request,
                human_input_initial_status="pending",
            )

        assert store.load() == before

    @pytest.mark.parametrize("effect_kind", ["update", "removal"])
    def test_human_input_advance_cannot_mask_active_authority_before_reseal(
        self,
        tmp_path,
        effect_kind,
    ):
        store = SquadStateStore(tmp_path / effect_kind)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        _seal_provider_human_input_via_advance(store)
        before = store.load()
        request = _human_input_request(
            source_kind="provider_escalation",
            source_state_revision=before["state_revision"],
            phase_id="next",
        )

        with pytest.raises(StateAdvanceError):
            _advance(
                store,
                "next",
                "init",
                _result(
                    "DONE",
                    {"replacement_fact": "must-not-commit"},
                    phase_id="next",
                ),
                transaction_state_updates=(
                    {
                        "blocked_decision": {"masked": True},
                        "recovery_instruction": {"masked": True},
                    }
                    if effect_kind == "update"
                    else None
                ),
                transaction_state_removals=(
                    ("blocked_decision", "recovery_instruction")
                    if effect_kind == "removal"
                    else ()
                ),
                human_input=request,
                human_input_initial_status="pending",
            )

        assert store.load() == before

    def test_human_input_claim_failure_retry_and_exhaustion_are_cas_transitions(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        pending = _seal_provider_human_input_via_advance(store)
        decision_id = pending["blocked_decision"]["id"]

        claimed_once = store.claim_human_input_decision(
            decision_id,
            expected_state_revision=pending["state_revision"],
        )
        assert claimed_once["blocked_decision"]["status"] == "resolving"
        assert claimed_once["blocked_decision"]["attempts"] == 1
        assert claimed_once["recovery_instruction"]["kind"] == "resolve_decision"

        retry = store.record_human_input_resolution_failure(
            decision_id,
            expected_state_revision=claimed_once["state_revision"],
            failure_code="provider_failed",
        )
        assert retry["blocked_decision"]["status"] == "pending"
        assert retry["blocked_decision"]["attempts"] == 1
        assert retry["blocked_decision"]["failure_code"] is None

        claimed_twice = store.claim_human_input_decision(
            decision_id,
            expected_state_revision=retry["state_revision"],
        )
        assert claimed_twice["blocked_decision"]["status"] == "resolving"
        assert claimed_twice["blocked_decision"]["attempts"] == 2

        failed = store.record_human_input_resolution_failure(
            decision_id,
            expected_state_revision=claimed_twice["state_revision"],
            failure_code="provider_failed",
        )
        assert failed["blocked_decision"]["status"] == "failed"
        assert failed["blocked_decision"]["attempts"] == 2
        assert failed["blocked_decision"]["failure_code"] == "provider_failed"
        assert failed["recovery_instruction"]["kind"] == "manual_diagnosis"
        assert failed["recovery_instruction"]["phase"] == ""
        assert "escalation_question" not in failed

    def test_v3_commander_override_persists_complete_resolution_audit(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize(
            "r1",
            "greenfield",
            "msg",
            0,
            "init",
            autonomy_mode="banzai",
        )
        pending = _seal_provider_human_input_via_advance(store)
        decision_id = pending["blocked_decision"]["id"]
        claimed = store.claim_human_input_decision(
            decision_id,
            expected_state_revision=pending["state_revision"],
        )

        resolved = store.apply_human_input_state_resolution(
            decision_id,
            expected_state_revision=claimed["state_revision"],
            resolution=HumanInputResolution(
                selected_option_id=None,
                answer_text="Use the safer bounded alternative.",
                resolved_by="COMMANDER",
            ),
            resolution_rationale="The alternative avoids an unsafe assumption.",
            resolution_confidence="high",
            state_updates={"status": "running", "phase": "next"},
            state_removals=(),
            resolved_at="2026-07-28T10:01:00+00:00",
        )

        decision = resolved["blocked_decision"]
        assert decision["schema_version"] == 3
        assert decision["recommendation_followed"] is False
        assert decision["resolution_rationale"] == (
            "The alternative avoids an unsafe assumption."
        )
        assert decision["resolution_confidence"] == "high"
        assert decision["override_reason"] == decision["resolution_rationale"]

    def test_human_input_setup_failure_fails_pending_without_claiming(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        pending = _seal_provider_human_input_via_advance(store)
        decision_id = pending["blocked_decision"]["id"]

        failed = store.fail_pending_human_input_decision(
            decision_id,
            expected_state_revision=pending["state_revision"],
            failure_code="decision_context_setup_failed",
        )

        assert failed["blocked_decision"]["status"] == "failed"
        assert failed["blocked_decision"]["attempts"] == 0
        assert failed["blocked_decision"]["failure_code"] == (
            "decision_context_setup_failed"
        )
        assert failed["recovery_instruction"]["kind"] == "manual_diagnosis"
        assert "escalation_question" not in failed

    def test_claim_rejects_attempt_limit_independently_of_schema_validation(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        pending = _seal_provider_human_input_via_advance(store)
        corrupted = deepcopy(pending)
        corrupted["blocked_decision"]["attempts"] = 2
        store._path.write_text(json.dumps(corrupted), encoding="utf-8")
        before = store._path.read_bytes()

        with (
            patch(
                "harness.squad_state.validate_blocked_decision",
                side_effect=lambda value: deepcopy(dict(value)),
            ),
            patch(
                "harness.squad_state.validate_decision_recovery_pair",
                return_value=None,
            ),
        ):
            with pytest.raises(StateAdvanceError, match="attempt"):
                store.claim_human_input_decision(
                    pending["blocked_decision"]["id"],
                    expected_state_revision=pending["state_revision"],
                )

        assert store._path.read_bytes() == before

    @pytest.mark.parametrize(
        ("status", "attempts"),
        [
            ("pending", 2),
            ("resolving", 0),
            ("failed", 3),
            ("resolved", 3),
        ],
    )
    def test_startup_recovery_rejects_corrupted_status_attempt_state(
        self,
        tmp_path,
        status,
        attempts,
    ):
        store = SquadStateStore(tmp_path / f"{status}-{attempts}")
        store.initialize("r1", "greenfield", "msg", 0, "init")
        pending = _seal_provider_human_input_via_advance(store)
        corrupted = deepcopy(pending)
        decision = corrupted["blocked_decision"]
        decision["status"] = status
        decision["attempts"] = attempts
        if status == "failed":
            decision["failure_code"] = "provider_failed"
            corrupted["recovery_instruction"].update(
                {
                    "kind": "manual_diagnosis",
                    "phase": "",
                }
            )
        elif status == "resolved":
            decision.update(
                {
                    "answer_text": "Resolved answer.",
                    "resolved_by": "COMMANDER",
                    "resolved_at": "2026-07-28T10:01:00+00:00",
                }
            )
            corrupted.pop("recovery_instruction")
        store._path.write_text(json.dumps(corrupted), encoding="utf-8")
        before = store._path.read_bytes()

        with pytest.raises(ValueError, match="attempt"):
            store.recover_interrupted_human_input_decision()

        assert store._path.read_bytes() == before

    @pytest.mark.parametrize("transition", ["resolution", "failure"])
    @pytest.mark.parametrize("save_then_raise", [False, True])
    def test_task6_fix_round1_human_input_usage_is_in_exact_attempt_cas(
        self,
        tmp_path,
        transition,
        save_then_raise,
    ):
        store = SquadStateStore(
            tmp_path / f"{transition}-{save_then_raise}"
        )
        store.initialize(
            "r1",
            "greenfield",
            "msg",
            0,
            "init",
            autonomy_mode="banzai",
        )
        pending = _seal_provider_human_input_via_advance(store)
        decision_id = pending["blocked_decision"]["id"]
        claimed = store.claim_human_input_decision(
            decision_id,
            expected_state_revision=pending["state_revision"],
        )
        before = deepcopy(claimed)
        original_save = store._save_unlocked

        def injected_save(state, **kwargs):
            if save_then_raise:
                original_save(state, **kwargs)
            raise OSError("injected human-input attempt save ambiguity")

        with patch.object(
            store,
            "_save_unlocked",
            side_effect=injected_save,
        ):
            if transition == "resolution":
                operation = lambda: store.apply_human_input_state_resolution(
                    decision_id,
                    expected_state_revision=claimed["state_revision"],
                    resolution=HumanInputResolution(
                        selected_option_id=None,
                        answer_text="Use the durable answer.",
                        resolved_by="COMMANDER",
                    ),
                    state_updates={"status": "running", "phase": "next"},
                    state_removals=(),
                    token_usage_delta=17,
                    resolution_rationale="The bounded answer is safer.",
                    resolution_confidence="medium",
                )
            else:
                operation = lambda: store.record_human_input_resolution_failure(
                    decision_id,
                    expected_state_revision=claimed["state_revision"],
                    failure_code="invalid_resolution_result",
                    token_usage_delta=17,
                )
            if save_then_raise:
                result = operation()
            else:
                with pytest.raises(StateAdvanceError):
                    operation()

        after = store.load()
        if not save_then_raise:
            assert after == before
            return
        assert result == after
        assert after["token_usage"] == 17
        assert after["state_revision"] == before["state_revision"] + 1
        assert after["blocked_decision"]["status"] == (
            "resolved" if transition == "resolution" else "pending"
        )

    @pytest.mark.parametrize("second_attempt", [False, True])
    def test_human_input_interrupted_resolution_recovers_or_exhausts(
        self,
        tmp_path,
        second_attempt,
    ):
        store = SquadStateStore(tmp_path / str(second_attempt))
        store.initialize("r1", "greenfield", "msg", 0, "init")
        pending = _seal_provider_human_input_via_advance(store)
        decision_id = pending["blocked_decision"]["id"]
        resolving = store.claim_human_input_decision(
            decision_id,
            expected_state_revision=pending["state_revision"],
        )
        if second_attempt:
            pending = store.record_human_input_resolution_failure(
                decision_id,
                expected_state_revision=resolving["state_revision"],
                failure_code="validation_failed",
            )
            resolving = store.claim_human_input_decision(
                decision_id,
                expected_state_revision=pending["state_revision"],
            )

        recovered = store.recover_interrupted_human_input_decision()

        if second_attempt:
            assert recovered["blocked_decision"]["status"] == "failed"
            assert recovered["blocked_decision"]["failure_code"] == (
                "resolution_attempts_exhausted"
            )
            assert recovered["recovery_instruction"]["kind"] == (
                "manual_diagnosis"
            )
            assert "escalation_question" not in recovered
        else:
            assert recovered["blocked_decision"]["status"] == "pending"
            assert recovered["blocked_decision"]["attempts"] == 1
            assert recovered["recovery_instruction"]["kind"] == (
                "resolve_decision"
            )

    def test_human_input_wrong_id_and_stale_revision_write_nothing(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        pending = _seal_provider_human_input_via_advance(store)
        before = store.load()

        with pytest.raises(StateAdvanceError):
            store.claim_human_input_decision(
                "dec-wrong",
                expected_state_revision=pending["state_revision"],
            )
        assert store.load() == before

        with pytest.raises(StateAdvanceError):
            store.claim_human_input_decision(
                pending["blocked_decision"]["id"],
                expected_state_revision=pending["state_revision"] - 1,
            )
        assert store.load() == before

    def test_human_input_resolution_retains_audit_and_removes_instruction(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        request = _human_input_request(
            source_kind="human_gate",
            source_state_revision=store.load()["state_revision"],
        )
        awaiting = store.set_human_input_decision(
            request,
            initial_status="awaiting_human",
        )
        original_decision = deepcopy(awaiting["blocked_decision"])

        resolved = store.apply_human_input_state_resolution(
            original_decision["id"],
            expected_state_revision=awaiting["state_revision"],
            resolution=HumanInputResolution(
                selected_option_id="approve",
                answer_text=None,
                resolved_by="user",
            ),
            state_updates={
                "status": "running",
                "phase": "next",
                "resolution_effect": "applied",
            },
            state_removals=("why_fail_count",),
        )

        decision = resolved["blocked_decision"]
        for field in (
            "id",
            "source_kind",
            "producer_id",
            "source_phase",
            "reason_code",
            "classification",
            "question",
            "options",
            "resolution_handler",
            "autonomy_mode",
            "source_state_revision",
            "created_at",
        ):
            assert decision[field] == original_decision[field]
        assert decision["status"] == "resolved"
        assert decision["selected_option_id"] == "approve"
        assert decision["answer_text"] is None
        assert decision["resolved_by"] == "user"
        assert decision["resolved_at"]
        assert decision["recommendation_followed"] is True
        assert decision["resolution_rationale"] is None
        assert decision["resolution_confidence"] is None
        assert decision["override_reason"] is None
        assert resolved["status"] == "running"
        assert resolved["phase"] == "next"
        assert resolved["resolution_effect"] == "applied"
        assert "why_fail_count" not in resolved
        assert "recovery_instruction" not in resolved
        assert "blocked_reason" not in resolved
        assert "escalation_question" not in resolved
        assert "escalation_options" not in resolved

    def test_human_input_resolution_canonicalizes_answer_before_follow_audit(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        request = _human_input_request(
            source_kind="human_gate",
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
                selected_option_id=" approve ",
                answer_text=None,
                resolved_by="user",
            ),
            state_updates={"status": "running", "phase": "next"},
            state_removals=(),
        )

        assert resolved["blocked_decision"]["selected_option_id"] == "approve"
        assert resolved["blocked_decision"]["recommendation_followed"] is True

    def test_human_input_resolved_audit_allows_later_unrelated_block(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        request = _human_input_request(
            source_kind="human_gate",
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
                resolved_by="user",
            ),
            state_updates={"status": "running", "phase": "next"},
            state_removals=(),
        )
        audit_record = deepcopy(resolved["blocked_decision"])

        store.set_blocked("provider_unavailable")

        blocked = store.load()
        assert blocked["state_revision"] == resolved["state_revision"] + 1
        assert blocked["status"] == "blocked"
        assert blocked["blocked_reason"] == "provider_unavailable"
        assert blocked["blocked_decision"] == audit_record
        assert "recovery_instruction" not in blocked
        assert "escalation_question" not in blocked
        assert "escalation_options" not in blocked

    def test_failure_diagnostic_cleans_stale_resolved_recovery(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        request = _human_input_request(
            source_kind="human_gate",
            source_state_revision=store.load()["state_revision"],
        )
        awaiting = store.set_human_input_decision(
            request,
            initial_status="awaiting_human",
        )
        stale_recovery = deepcopy(awaiting["recovery_instruction"])
        resolved = store.apply_human_input_state_resolution(
            awaiting["blocked_decision"]["id"],
            expected_state_revision=awaiting["state_revision"],
            resolution=HumanInputResolution(
                selected_option_id="approve",
                answer_text=None,
                resolved_by="user",
            ),
            state_updates={"status": "running", "phase": "phase3-plan2"},
            state_removals=(),
        )
        legacy = deepcopy(resolved)
        legacy["recovery_instruction"] = stale_recovery
        store._path.write_text(json.dumps(legacy), encoding="utf-8")

        persisted = store.merge_advance_failure_diagnostic(
            from_phase="phase3-plan2",
            expected_state_revision=resolved["state_revision"],
            expected_previous_dispatch_sha256=None,
            updates={
                "status": "blocked",
                "controller_contract_error": {"message": "contract failed"},
            },
        )

        blocked = store.load()
        assert persisted is True
        assert blocked["status"] == "blocked"
        assert blocked["controller_contract_error"] == {
            "message": "contract failed",
        }
        assert blocked["blocked_decision"] == resolved["blocked_decision"]
        assert "recovery_instruction" not in blocked

    def test_failure_diagnostic_preserves_controller_recovery_after_resolved_audit(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        request = _human_input_request(
            source_kind="human_gate",
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
                resolved_by="user",
            ),
            state_updates={"status": "running", "phase": "phase3-consensus"},
            state_removals=(),
        )
        recovery = controller_contract_recovery("phase3-consensus").to_dict()

        persisted = store.merge_advance_failure_diagnostic(
            from_phase="phase3-consensus",
            expected_state_revision=resolved["state_revision"],
            expected_previous_dispatch_sha256=None,
            updates={
                "status": "blocked",
                "blocked_reason": "controller_state_contract_validation_failed",
                "controller_contract_error": {"message": "contract failed"},
                "recovery_instruction": recovery,
            },
        )

        blocked = store.load()
        assert persisted is True
        assert blocked["status"] == "blocked"
        assert blocked["recovery_instruction"] == recovery
        assert "blocked_decision" not in blocked

    def test_human_input_resolution_detaches_updates_before_validation(
        self,
        tmp_path,
    ):
        class SwitchingMapping(Mapping):
            def __getitem__(self, key):
                if key != "status":
                    raise KeyError(key)
                return "running"

            def __iter__(self):
                return iter(("status",))

            def __len__(self):
                return 1

            def items(self):
                return (("escalation_question", "injected after validation"),)

        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        request = _human_input_request(
            source_kind="human_gate",
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
                resolved_by="user",
            ),
            state_updates=SwitchingMapping(),
            state_removals=(),
        )

        assert resolved == store.load()
        assert resolved["status"] == "running"
        assert "escalation_question" not in resolved

    def test_human_input_shared_commit_attempts_exact_complete_postimage(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        before = store.load()
        request = _human_input_request(
            source_kind="human_gate",
            source_state_revision=before["state_revision"],
        )
        original_save = store._save_unlocked
        attempted = {}

        def save_then_raise(state, **kwargs):
            attempted.update(deepcopy(state))
            original_save(state, **kwargs)
            raise OSError("injected post-save ambiguity")

        with patch.object(store, "_save_unlocked", side_effect=save_then_raise):
            sealed = store.set_human_input_decision(
                request,
                initial_status="awaiting_human",
            )

        assert sealed == store.load()
        assert attempted == sealed
        assert attempted["state_revision"] == before["state_revision"] + 1
        assert isinstance(attempted["updated_at"], str)

    @pytest.mark.parametrize(
        "drift",
        [
            "missing_updated_at",
            "stale_updated_at",
            "malformed_updated_at",
            "state_revision",
        ],
    )
    def test_human_input_shared_commit_rejects_near_postimage_drift(
        self,
        tmp_path,
        drift,
    ):
        store = SquadStateStore(tmp_path / drift)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        before = store.load()
        request = _human_input_request(
            source_kind="human_gate",
            source_state_revision=before["state_revision"],
        )
        original_save = store._save_unlocked

        def save_drift_then_raise(state, **kwargs):
            saved = original_save(state, **kwargs)
            if drift == "missing_updated_at":
                saved.pop("updated_at")
            elif drift == "stale_updated_at":
                saved["updated_at"] = before["updated_at"]
            elif drift == "malformed_updated_at":
                saved["updated_at"] = "not-a-timestamp"
            else:
                saved["state_revision"] += 1
            store._path.write_text(json.dumps(saved, indent=2))
            raise OSError("injected near-postimage ambiguity")

        with patch.object(
            store,
            "_save_unlocked",
            side_effect=save_drift_then_raise,
        ):
            with pytest.raises(StateAdvanceError):
                store.set_human_input_decision(
                    request,
                    initial_status="awaiting_human",
                )

        assert store.load() != before

    def test_generic_save_preserves_active_decision_v3_authority_exactly(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        request = _human_input_request(
            source_kind="human_gate",
            source_state_revision=store.load()["state_revision"],
        )
        sealed = store.set_human_input_decision(
            request,
            initial_status="awaiting_human",
        )
        candidate = deepcopy(sealed)
        candidate["unrelated_note"] = "preserved"

        store.save(candidate)

        saved = store.load()
        assert saved["state_revision"] == sealed["state_revision"] + 1
        assert saved["unrelated_note"] == "preserved"
        for field in (
            "blocked_decision",
            "recovery_instruction",
            "phase",
            "status",
            "blocked_reason",
            "escalation_question",
            "escalation_options",
        ):
            assert saved[field] == sealed[field]

    @pytest.mark.parametrize(
        "field",
        [
            "blocked_decision",
            "recovery_instruction",
            "phase",
            "status",
            "blocked_reason",
            "escalation_question",
            "escalation_options",
        ],
    )
    def test_generic_save_rejects_active_decision_v3_authority_changes(
        self,
        tmp_path,
        field,
    ):
        store = SquadStateStore(tmp_path / field)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        request = _human_input_request(
            source_kind="human_gate",
            source_state_revision=store.load()["state_revision"],
        )
        sealed = store.set_human_input_decision(
            request,
            initial_status="awaiting_human",
        )
        candidate = deepcopy(sealed)
        if field == "blocked_decision":
            candidate[field]["question"] = "Mutated"
        elif field == "recovery_instruction":
            candidate[field]["reason_code"] = "mutated"
        elif field == "phase":
            candidate[field] = "next"
        elif field == "status":
            candidate[field] = "running"
        elif field == "blocked_reason":
            candidate[field] = "mutated"
        elif field == "escalation_question":
            candidate.pop(field)
        else:
            candidate[field] = []

        with pytest.raises(StateAdvanceError) as exc:
            store.save(candidate)

        if field == "recovery_instruction":
            assert exc.value.json_path == "$.recovery_instruction"
            assert exc.value.validator == "human_input_authority"

        assert store.load() == sealed

    def test_generic_save_cannot_create_or_clear_decision_v3_authority(
        self,
        tmp_path,
    ):
        source = SquadStateStore(tmp_path / "source")
        source.initialize("source", "greenfield", "msg", 0, "init")
        request = _human_input_request(
            source_kind="human_gate",
            source_state_revision=source.load()["state_revision"],
        )
        sealed = source.set_human_input_decision(
            request,
            initial_status="awaiting_human",
        )

        target = SquadStateStore(tmp_path / "target")
        target.initialize("target", "greenfield", "msg", 0, "init")
        target_before = target.load()
        candidate = deepcopy(target_before)
        for field in (
            "blocked_decision",
            "recovery_instruction",
            "blocked_reason",
            "escalation_question",
            "escalation_options",
        ):
            candidate[field] = deepcopy(sealed[field])
        candidate["status"] = "blocked"
        with pytest.raises(StateAdvanceError):
            target.save(candidate)
        assert target.load() == target_before

        cleared = deepcopy(sealed)
        cleared.pop("blocked_decision")
        cleared.pop("recovery_instruction")
        with pytest.raises(StateAdvanceError):
            source.save(cleared)
        assert source.load() == sealed

    def test_generic_save_cannot_mutate_legacy_v2_decision_authority(
        self,
        tmp_path,
    ):
        store = _store(tmp_path)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        request = _human_input_request(
            source_kind="human_gate",
            source_state_revision=store.load()["state_revision"],
        )
        sealed = store.set_human_input_decision(
            request,
            initial_status="awaiting_human",
        )
        legacy = deepcopy(sealed)
        legacy_decision = legacy["blocked_decision"]
        legacy_decision["schema_version"] = 2
        for field in (
            "recommended_option_id",
            "recommended_action",
            "automatic_eligible",
            "recommendation_rationale",
            "recommendation_confidence",
            "recommendation_authority",
            "recommendation_evidence",
            "resolution_rationale",
            "resolution_confidence",
            "recommendation_followed",
            "override_reason",
        ):
            legacy_decision.pop(field)
        store._path.write_text(json.dumps(legacy), encoding="utf-8")

        candidate = deepcopy(legacy)
        candidate["blocked_decision"]["question"] = "Mutated"
        with pytest.raises(StateAdvanceError, match="generic state writes"):
            store.save(candidate)

        assert store.load() == legacy

    @pytest.mark.parametrize("schema_version", [2, 3])
    def test_generic_save_cannot_remove_resolved_recovery_authority(
        self,
        tmp_path,
        schema_version,
    ):
        store = SquadStateStore(tmp_path / f"schema-{schema_version}")
        store.initialize("r1", "greenfield", "msg", 0, "init")
        request = _human_input_request(
            source_kind="human_gate",
            source_state_revision=store.load()["state_revision"],
        )
        awaiting = store.set_human_input_decision(
            request,
            initial_status="awaiting_human",
        )
        stale_recovery = deepcopy(awaiting["recovery_instruction"])
        resolved = store.apply_human_input_state_resolution(
            awaiting["blocked_decision"]["id"],
            expected_state_revision=awaiting["state_revision"],
            resolution=HumanInputResolution(
                selected_option_id="approve",
                answer_text=None,
                resolved_by="user",
            ),
            state_updates={"status": "running", "phase": "next"},
            state_removals=(),
        )
        persisted = deepcopy(resolved)
        persisted["recovery_instruction"] = stale_recovery
        if schema_version == 2:
            persisted["blocked_decision"]["schema_version"] = 2
            for field in (
                "recommended_option_id",
                "recommended_action",
                "automatic_eligible",
                "recommendation_rationale",
                "recommendation_confidence",
                "recommendation_authority",
                "recommendation_evidence",
                "resolution_rationale",
                "resolution_confidence",
                "recommendation_followed",
                "override_reason",
            ):
                persisted["blocked_decision"].pop(field)
        store._path.write_text(json.dumps(persisted), encoding="utf-8")
        candidate = deepcopy(persisted)
        candidate.pop("recovery_instruction")

        with pytest.raises(StateAdvanceError, match="recovery authority"):
            store.save(candidate)

        assert store.load() == persisted

    @pytest.mark.parametrize("terminal_status", ["resolved", "failed"])
    def test_generic_save_cannot_replace_terminal_decision_v3_but_seal_can(
        self,
        tmp_path,
        terminal_status,
    ):
        store = SquadStateStore(tmp_path / terminal_status)
        store.initialize("r1", "greenfield", "msg", 0, "init")
        request = _human_input_request(
            source_kind="human_gate",
            source_state_revision=store.load()["state_revision"],
        )
        sealed = store.set_human_input_decision(
            request,
            initial_status=(
                "awaiting_human" if terminal_status == "resolved" else "pending"
            ),
        )
        decision_id = sealed["blocked_decision"]["id"]
        if terminal_status == "resolved":
            terminal = store.apply_human_input_state_resolution(
                decision_id,
                expected_state_revision=sealed["state_revision"],
                resolution=HumanInputResolution(
                    selected_option_id="approve",
                    answer_text=None,
                    resolved_by="user",
                ),
                state_updates={"status": "running", "phase": "next"},
                state_removals=(),
            )
        else:
            first_claim = store.claim_human_input_decision(
                decision_id,
                expected_state_revision=sealed["state_revision"],
            )
            retry = store.record_human_input_resolution_failure(
                decision_id,
                expected_state_revision=first_claim["state_revision"],
                failure_code="provider_failed",
            )
            second_claim = store.claim_human_input_decision(
                decision_id,
                expected_state_revision=retry["state_revision"],
            )
            terminal = store.record_human_input_resolution_failure(
                decision_id,
                expected_state_revision=second_claim["state_revision"],
                failure_code="provider_failed",
            )

        prompt_recreation = deepcopy(terminal)
        prompt_recreation.update(
            {
                "status": "blocked",
                "blocked_reason": "recreated",
                "escalation_question": "Recreate the terminal prompt?",
                "escalation_options": [],
                "escalation_resolved": False,
            }
        )
        with pytest.raises(StateAdvanceError):
            store.save(prompt_recreation)
        assert store.load() == terminal

        candidate = deepcopy(terminal)
        candidate.pop("blocked_decision")
        candidate.pop("recovery_instruction", None)
        with pytest.raises(StateAdvanceError):
            store.save(candidate)
        assert store.load() == terminal

        replacement = _human_input_request(
            source_kind="human_gate",
            source_state_revision=terminal["state_revision"],
            phase_id=terminal["phase"],
        )
        resealed = store.set_human_input_decision(
            replacement,
            initial_status="awaiting_human",
        )
        assert resealed["blocked_decision"]["id"] != decision_id
        assert resealed["blocked_decision"]["status"] == "awaiting_human"
