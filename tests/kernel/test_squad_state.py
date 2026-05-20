"""Tests for SquadStateStore."""
import sys
from pathlib import Path

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

    def test_advance_applies_state_updates(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        store.advance("init", "phase1-discover",
                      _result("DONE", {"coverage_pct": 72}))
        assert store.load()["coverage_pct"] == 72

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
