"""Tests for SquadAgentResult and echelon_result extraction."""
import sys
from pathlib import Path

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.squad_provider import SquadAgentResult, _extract_echelon_result


class TestSquadAgentResult:
    def _result(self, echelon_result=None, exit_code=0, timed_out=False):
        return SquadAgentResult(
            exit_code=exit_code,
            echelon_result=echelon_result,
            raw_output="",
            duration_ms=100,
            timed_out=timed_out,
        )

    def test_verdict_returns_none_when_no_echelon_result(self):
        assert self._result().verdict is None

    def test_verdict_from_echelon_result(self):
        r = self._result({"verdict": "DONE", "state_updates": {}})
        assert r.verdict == "DONE"

    def test_state_updates_empty_when_no_echelon_result(self):
        assert self._result().state_updates == {}

    def test_state_updates_from_echelon_result(self):
        r = self._result({"verdict": "DONE", "state_updates": {"coverage_pct": 72}})
        assert r.state_updates == {"coverage_pct": 72}

    def test_blocked_true_when_verdict_blocked(self):
        assert self._result({"verdict": "BLOCKED", "state_updates": {}}).blocked is True

    def test_blocked_true_when_timed_out(self):
        assert self._result(timed_out=True).blocked is True

    def test_blocked_true_when_nonzero_exit(self):
        assert self._result(exit_code=1).blocked is True

    def test_blocked_false_when_done(self):
        assert self._result({"verdict": "DONE", "state_updates": {}}, exit_code=0).blocked is False


class TestExtractEchelonResult:
    def test_returns_none_when_absent(self):
        assert _extract_echelon_result("no result here") is None

    def test_extracts_bare_block(self):
        raw = """Some output.

echelon_result:
  verdict: DONE
  phase_id: re-extract-1-analyze
  state_updates:
    coverage_pct: 72
"""
        result = _extract_echelon_result(raw)
        assert result["verdict"] == "DONE"
        assert result["state_updates"]["coverage_pct"] == 72

    def test_extracts_from_fenced_yaml(self):
        raw = """
```yaml
echelon_result:
  verdict: PASS
  state_updates: {}
```
"""
        result = _extract_echelon_result(raw)
        assert result["verdict"] == "PASS"

    def test_returns_none_on_malformed_yaml(self):
        raw = "echelon_result:\n  verdict: [unclosed"
        assert _extract_echelon_result(raw) is None

    def test_extracts_last_occurrence(self):
        raw = """echelon_result:
  verdict: FAIL
  state_updates: {}

Later...

echelon_result:
  verdict: DONE
  state_updates: {}
"""
        result = _extract_echelon_result(raw)
        assert result["verdict"] == "DONE"
