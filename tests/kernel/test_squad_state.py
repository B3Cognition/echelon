"""Tests for SquadStateStore."""
import sys
from pathlib import Path
from unittest.mock import patch

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.squad_state import SquadStateStore
from harness.squad_provider import SquadAgentResult


def _store(tmp_path: Path) -> SquadStateStore:
    return SquadStateStore(tmp_path / "squad/run-test")


def _result(verdict="DONE", updates=None) -> SquadAgentResult:
    return SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": verdict, "state_updates": updates or {}},
        raw_output="",
        duration_ms=100,
        timed_out=False,
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

    def test_advance_updates_phase(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        store.advance("init", "phase1-discover", _result())
        assert store.current_phase() == "phase1-discover"

    def test_advance_writes_last_dispatch(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        store.advance("init", "phase1-discover", _result("DONE"))
        ld = store.load()["last_dispatch"]
        assert ld["phase_id"] == "init"
        assert ld["verdict"] == "DONE"

    def test_advance_records_completed_phase_provenance(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        store.advance("phase1-constitution", "phase1-what", _result("DONE"))

        assert store.load()["completed_phases"] == ["phase1-constitution"]

    def test_advance_applies_state_updates(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        store.advance("init", "phase1-discover",
                      _result("DONE", {"coverage_pct": 72}))
        assert store.load()["coverage_pct"] == 72

    def test_advance_blocks_invalid_result_without_mutating_state(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "DONE",
                "state_updates": {
                    "coverage_pct": 72,
                    "last_dispatch": {"phase_id": "fake"},
                },
            },
            raw_output="",
            duration_ms=100,
            timed_out=False,
        )

        store.advance("init", "phase1-discover", result)

        state = store.load()
        assert state["status"] == "blocked"
        assert state["phase"] == "init"
        assert state["completed_phases"] == []
        assert "coverage_pct" not in state
        assert "echelon_result validation failed" in state["blocked_reason"]

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

    def test_state_updates_status_routes_through_guard(self, tmp_path, caplog):
        import logging
        from harness.squad_provider import SquadAgentResult
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        result = SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {"status": "done"}},
            raw_output="",
            duration_ms=10,
            timed_out=False,
        )
        with caplog.at_level(logging.WARNING, logger="harness.squad_state"):
            store.advance("init", "phase1-discover", result)
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

    def test_state_updates_token_decrease_warns(self, tmp_path, caplog):
        import logging
        store = SquadStateStore(tmp_path / "squad/run-test")
        store.initialize("r1", "semi", "msg", 0, "init")
        store.increment_token_usage(1_000)
        result = _result("DONE", {"token_usage": 10})
        with caplog.at_level(logging.WARNING, logger="harness.squad_state"):
            store.advance("init", "phase1-discover", result)
        assert "token_usage decreased" in caplog.text


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
        store.advance("init", "phase1-discover", _result())
        assert self._ts(store) >= t0
