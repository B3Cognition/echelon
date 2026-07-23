"""Tests for SquadStateStore."""
import sys
from dataclasses import replace
from pathlib import Path
from pathlib import PurePath
from unittest.mock import patch

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.phase_graph import PhaseGraph, PhaseNode
from harness.controller_state_contracts import (
    ControllerStateContractViolation,
)
from harness.prepared_phase_result import PreparedPhaseResult, prepare_phase_result
from harness.squad_state import StateAdvanceError, SquadStateStore
from harness.squad_provider import SquadAgentResult
from harness.state_transaction_namespace import (
    PENDING_EXTERNAL_PUBLICATION_KEY,
)

DEFINITION = EXT_ROOT / "extension/workflow/definition.yaml"
EXT_YML = EXT_ROOT / "extension/extension.yml"
VALID_MARKER = {
    "schema_version": 1,
    "transaction_id": "a" * 32,
    "manifest_sha256": "b" * 64,
}


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
    node = PhaseGraph(DEFINITION, EXT_YML).get("phase3-tasks-lexicon")
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
    token_usage_delta: int = 0,
    transaction_state_updates: dict[str, object] | None = None,
    transaction_state_removals: object = (),
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
        token_usage_delta=token_usage_delta,
        transaction_state_updates=transaction_state_updates,
        transaction_state_removals=transaction_state_removals,
    )
    return store.advance(from_phase, to_phase, decision)


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

    def test_stale_advance_never_runs_before_commit_side_effect(
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
        side_effects: list[str] = []

        with pytest.raises(StateAdvanceError) as raised:
            store.advance(
                "repair",
                "next",
                decision,
                before_commit=lambda: side_effects.append("published"),
            )

        assert raised.value.validator == "stale_state"
        assert side_effects == []
        assert store.load()["winner_marker"] is True

    def test_before_commit_failure_does_not_persist_routing_state(
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

        def reject_publication() -> None:
            raise RuntimeError("publication rejected")

        with pytest.raises(RuntimeError, match="publication rejected"):
            store.advance(
                "repair",
                "next",
                decision,
                before_commit=reject_publication,
            )

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
        with patch("harness.squad_state.os.fsync") as mock_fsync:
            store.save(store.load())
        mock_fsync.assert_called_once()

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
