"""Tests for SquadAgentResult and echelon_result extraction."""
import sys
from pathlib import Path

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.squad_provider import (
    SquadAgentResult,
    _extract_echelon_result,
    _extract_strict_echelon_result,
    _validate_or_block_echelon_result,
)


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

    def test_strict_extraction_accepts_one_bare_complete_envelope(self):
        raw = """echelon_result:
  verdict: DECISION_RESOLVED
  state_updates: {}
  journal_entries: []
  decision:
    selected_option_id: approve
    answer_text: null
    rationale: Best exact allowed option.
    confidence: high
"""

        result = _extract_strict_echelon_result(raw)

        assert result is not None
        assert result["verdict"] == "DECISION_RESOLVED"
        assert result["decision"]["selected_option_id"] == "approve"

    @pytest.mark.parametrize(
        "raw",
        [
            (
                "echelon_result:\n"
                "  verdict: DECISION_RESOLVED\n"
                "  state_updates: {}\n"
                "  journal_entries: []\n"
                "  decision:\n"
                "    selected_option_id: reject\n"
                "    answer_text: null\n"
                "    rationale: First answer.\n"
                "    confidence: low\n\n"
                "echelon_result:\n"
                "  verdict: DECISION_RESOLVED\n"
                "  state_updates: {}\n"
                "  journal_entries: []\n"
                "  decision:\n"
                "    selected_option_id: approve\n"
                "    answer_text: null\n"
                "    rationale: Conflicting second answer.\n"
                "    confidence: high\n"
            ),
            (
                "```yaml\n"
                "echelon_result:\n"
                "  verdict: DECISION_RESOLVED\n"
                "  state_updates: {}\n"
                "  journal_entries: []\n"
                "  decision: {}\n"
                "```\n"
            ),
            (
                "Here is the answer.\n"
                "echelon_result:\n"
                "  verdict: DECISION_RESOLVED\n"
                "  state_updates: {}\n"
                "  journal_entries: []\n"
                "  decision: {}\n"
            ),
            (
                "echelon_result:\n"
                "  verdict: DECISION_RESOLVED\n"
                "  state_updates: {}\n"
                "  journal_entries: []\n"
                "  decision: {}\n"
                "This is trailing prose.\n"
            ),
            (
                "echelon_result:\n"
                "  verdict: DECISION_RESOLVED\n"
                "  state_updates: {}\n"
                "  journal_entries: []\n"
                "  decision:\n"
                "    selected_option_id: approve\n"
                "    answer_text: null\n"
                "    rationale: Evidence says: approve.\n"
                "    confidence: high\n"
            ),
        ],
        ids=(
            "duplicate",
            "fenced",
            "leading_prose",
            "trailing_prose",
            "repair_required",
        ),
    )
    def test_strict_extraction_rejects_non_bare_or_repaired_output(self, raw):
        assert _extract_strict_echelon_result(raw) is None

    def test_recovers_unquoted_colon_in_product_input_rationale(self):
        raw = """echelon_result:
  verdict: COMPLETE
  state_updates:
    lexicon_pass: true
  product_input_updates:
    - input_unit_id: IN-REQ-A1CDF9D624B1
      disposition: included
      rationale: The factual premise is challenged: no entity-tagging model exists.
      spec_ids: [FR-100]
      task_ids: []
      targets: []
  journal_entries: []
── done  1 turns · 42s · $2.3042 ──
"""

        result = _extract_echelon_result(raw)

        assert result is not None
        assert result["state_updates"]["lexicon_pass"] is True
        assert result["product_input_updates"] == [{
            "input_unit_id": "IN-REQ-A1CDF9D624B1",
            "disposition": "included",
            "rationale": "The factual premise is challenged: no entity-tagging model exists.",
            "spec_ids": ["FR-100"],
            "task_ids": [],
            "targets": [],
        }]

    # ── Legacy fenced block format (```echelon_result) ─────────────────────
    # Kept as a compatibility parser for older run logs and provider drift.
    # Current prompts require an unfenced YAML root block as the final output.

    def test_extracts_fenced_block_verdict(self):
        raw = """Some preamble.

```echelon_result
verdict: FAIL
state_updates:
  quality_scores:
    - pass: false
```
"""
        result = _extract_echelon_result(raw)
        assert result is not None
        assert result["verdict"] == "FAIL"

    def test_extracts_fenced_block_state_updates(self):
        raw = """```echelon_result
verdict: FAIL
state_updates:
  quality_scores:
    - pass: false
  escalation_question: |
    Q1: Is AR required?
  blocked_reason: "WHY1: critical issues"
journal_entries:
  - id: null
    type: quality_check
    agent: WHY
```
"""
        result = _extract_echelon_result(raw)
        assert result["state_updates"]["quality_scores"] == [{"pass": False}]
        assert "Q1:" in result["state_updates"]["escalation_question"]

    def test_fenced_block_wins_when_last(self):
        """When YAML-key block appears first and fenced block appears last, pick fenced."""
        raw = """echelon_result:
  verdict: YAML_KEY_EARLIER
  state_updates: {}

... agent continues writing ...

```echelon_result
verdict: FENCED_LATER
state_updates:
  quality_scores:
    - pass: true
```
"""
        result = _extract_echelon_result(raw)
        assert result["verdict"] == "FENCED_LATER"

    def test_yaml_key_wins_when_last(self):
        """When fenced block appears first and YAML-key block appears last, pick YAML-key."""
        raw = """```echelon_result
verdict: FENCED_EARLIER
state_updates: {}
```

... commander writes its own result ...

echelon_result:
  verdict: YAML_KEY_LATER
  state_updates:
    next_phase: phase1-discover
"""
        result = _extract_echelon_result(raw)
        assert result["verdict"] == "YAML_KEY_LATER"
        assert result["state_updates"]["next_phase"] == "phase1-discover"

    def test_fenced_block_journal_entries_parsed(self):
        raw = """```echelon_result
verdict: PASS
state_updates:
  quality_scores:
    - pass: true
journal_entries:
  - id: null
    type: quality_check
    agent: WHY
    data:
      pass: true
```
"""
        result = _extract_echelon_result(raw)
        assert result["verdict"] == "PASS"
        entries = result.get("journal_entries", [])
        assert len(entries) == 1
        assert entries[0]["type"] == "quality_check"

    def test_rejects_xml_style_echelon_result_block(self):
        raw = """
<echelon_result>
  <verdict>COMPLETE</verdict>
  <output_files>
    - specs/006-element-creator/test-strategy.md
  </output_files>
  <journal_entries>
    - type: decision
      phase: phase3-sentinel
  </journal_entries>
</echelon_result>
"""
        assert _extract_echelon_result(raw) is None


class TestValidateOrBlockEchelonResult:
    def test_invalid_parsed_result_becomes_blocked_result(self):
        result = _validate_or_block_echelon_result(
            ["not", "an", "object"],
            raw="echelon_result:\n  - bad",
            exit_code=0,
            duration_ms=10,
        )

        assert result["verdict"] == "BLOCKED"
        assert "must be an object" in result["state_updates"]["blocked_reason"]

    def test_validation_block_includes_debug_path_when_enabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ECHELON_DEBUG_RAW_DIR", str(tmp_path))

        result = _validate_or_block_echelon_result(
            {"verdict": "MAYBE", "state_updates": {}},
            raw="echelon_result:\n  verdict: MAYBE\n  state_updates: {}",
            exit_code=0,
            duration_ms=10,
        )

        debug_path = Path(result["state_updates"]["echelon_result_debug_path"])
        assert debug_path.exists()
        assert debug_path.read_text() == "echelon_result:\n  verdict: MAYBE\n  state_updates: {}"
