"""
Unit tests for scripts/belief-parser.py

Run with:
    pytest tests/unit/test_belief_parser.py -v
"""

import json
import os
import sys
import textwrap
from datetime import date, timedelta
from pathlib import Path

import pytest
from freezegun import freeze_time

# Add scripts/ directory to path so we can import the module directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "belief_parser",
    Path(__file__).parent.parent.parent / "scripts" / "belief-parser.py",
)
belief_parser = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(belief_parser)

FIXTURES = Path(__file__).parent.parent.parent / "scripts" / "belief-parser-fixtures"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _today() -> str:
    return date.today().isoformat()


def _days_from_now(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


# ---------------------------------------------------------------------------
# 1. YAML config annotation parsing
# ---------------------------------------------------------------------------


class TestYamlAnnotationParsing:
    def test_full_multiline_belief_parsed(self):
        """Multi-line @belief(…) block populates all fields."""
        beliefs = belief_parser.parse_config_file(FIXTURES / "sample-config.yml")
        hit = next(b for b in beliefs if b["config_key"] == "analysis.convergence_delta")
        assert hit["claim"] == (
            "Convergence delta of 0.02 is optimal for spec quality improvement detection"
        )
        assert hit["verified_date"] == "2026-03-28"
        assert hit["expires_date"] == "2026-09-28"
        assert hit["anchor_url"] == "config-template.yml analysis section"
        assert hit["confidence"] == pytest.approx(0.75)
        assert hit["severity"] == "medium"
        assert hit["config_value"] == "0.02"

    def test_minimal_inline_belief_parsed(self):
        """Single-line @belief(claim: "…") requires only claim field."""
        beliefs = belief_parser.parse_config_file(FIXTURES / "sample-config.yml")
        hit = next(b for b in beliefs if b["config_key"] == "analysis.max_squad_iterations")
        assert hit["claim"] == "Max 5 iterations prevents infinite loops"
        assert hit["config_value"] == "5"
        # Optional fields default to None / not present
        assert hit.get("expires_date") is None
        assert hit.get("confidence") is None

    def test_plain_comment_not_parsed_as_belief(self):
        """Ordinary comments must not produce beliefs."""
        beliefs = belief_parser.parse_config_file(FIXTURES / "sample-config.yml")
        keys = [b["config_key"] for b in beliefs]
        assert "analysis.mode" not in keys

    def test_key_without_annotation_not_included(self):
        """Config keys with no annotation must not appear in output."""
        beliefs = belief_parser.parse_config_file(FIXTURES / "sample-config.yml")
        keys = [b["config_key"] for b in beliefs]
        assert "no_annotation_key" not in keys

    def test_nested_key_dotted_path(self):
        """Deeply nested YAML key produces dotted config_key path."""
        beliefs = belief_parser.parse_config_file(FIXTURES / "sample-config.yml")
        hit = next(
            (b for b in beliefs if b["config_key"] == "nested.deep.some_value"), None
        )
        assert hit is not None
        assert hit["claim"] == "Nested key parsing must work for deeply nested config values"

    def test_source_file_recorded(self):
        """source_file must be the filename (not full path)."""
        beliefs = belief_parser.parse_config_file(FIXTURES / "sample-config.yml")
        assert all(b["source_file"] == "sample-config.yml" for b in beliefs)

    def test_source_line_recorded_and_positive(self):
        """source_line must be a positive integer."""
        beliefs = belief_parser.parse_config_file(FIXTURES / "sample-config.yml")
        for b in beliefs:
            assert isinstance(b["source_line"], int)
            assert b["source_line"] > 0

    def test_belief_id_format(self):
        """belief_id must start with 'config:' for config-sourced beliefs."""
        beliefs = belief_parser.parse_config_file(FIXTURES / "sample-config.yml")
        for b in beliefs:
            assert b["belief_id"].startswith("config:")

    def test_empty_config_returns_empty_list(self):
        """File with zero annotations must yield [] without raising."""
        beliefs = belief_parser.parse_config_file(FIXTURES / "empty-config.yml")
        assert beliefs == []

    def test_count_of_beliefs_in_sample(self):
        """Sanity check: sample-config.yml should yield exactly 6 beliefs."""
        beliefs = belief_parser.parse_config_file(FIXTURES / "sample-config.yml")
        assert len(beliefs) == 6


# ---------------------------------------------------------------------------
# 2. Markdown Belief Register parsing
# ---------------------------------------------------------------------------


class TestMarkdownBeliefRegisterParsing:
    def test_all_rows_parsed(self):
        """All 5 table rows must be extracted from sample-agent.md."""
        beliefs = belief_parser.parse_agent_file(FIXTURES / "sample-agent.md")
        assert len(beliefs) == 5

    def test_row_fields_populated(self):
        """Belief fields map correctly from markdown columns."""
        beliefs = belief_parser.parse_agent_file(FIXTURES / "sample-agent.md")
        cmd001 = next(b for b in beliefs if b["belief_id"] == "CMD-001")
        assert cmd001["claim"] == "Evidence hierarchy has 5 ranks"
        assert cmd001["verified_date"] == "2026-03-28"
        assert cmd001["expires_date"] == "2026-09-28"
        assert cmd001["anchor_url"] == "commander.md"
        assert cmd001["confidence"] == pytest.approx(0.95)
        assert cmd001["severity"] == "high"

    def test_source_file_is_md_filename(self):
        """source_file must be the .md filename."""
        beliefs = belief_parser.parse_agent_file(FIXTURES / "sample-agent.md")
        assert all(b["source_file"] == "sample-agent.md" for b in beliefs)

    def test_belief_id_preserved_from_table(self):
        """Belief IDs from the markdown table are used verbatim."""
        beliefs = belief_parser.parse_agent_file(FIXTURES / "sample-agent.md")
        ids = {b["belief_id"] for b in beliefs}
        assert ids == {"CMD-001", "CMD-002", "CMD-003", "CMD-004", "CMD-005"}

    def test_no_belief_register_section_returns_empty(self):
        """Markdown with no Belief Register table yields []."""
        md_path = FIXTURES / "no-beliefs.md"
        md_path.write_text("# Agent\n\nNo beliefs here.\n")
        try:
            beliefs = belief_parser.parse_agent_file(md_path)
            assert beliefs == []
        finally:
            md_path.unlink()


# ---------------------------------------------------------------------------
# 3. Status classification
# ---------------------------------------------------------------------------


class TestStatusClassification:
    def _make_belief(self, expires=None, confidence=None):
        return {
            "belief_id": "test:x",
            "claim": "test",
            "verified_date": "2026-01-01",
            "expires_date": expires,
            "confidence": confidence,
            "severity": "medium",
            "source_file": "test.yml",
            "source_line": 1,
        }

    def test_expired_status(self):
        """Belief with expires_date in the past is 'expired'."""
        b = self._make_belief(expires="2025-01-01")
        assert belief_parser.classify_status(b) == "expired"

    def test_approaching_expiry_status(self):
        """Belief expiring within 30 days is 'approaching_expiry'."""
        soon = _days_from_now(15)
        b = self._make_belief(expires=soon)
        assert belief_parser.classify_status(b) == "approaching_expiry"

    def test_approaching_expiry_boundary(self):
        """Belief expiring exactly 30 days from now is 'approaching_expiry'."""
        boundary = _days_from_now(30)
        b = self._make_belief(expires=boundary)
        assert belief_parser.classify_status(b) == "approaching_expiry"

    def test_fresh_status(self):
        """Belief with far-future expiry and good confidence is 'fresh'."""
        b = self._make_belief(expires="2030-01-01", confidence=0.80)
        assert belief_parser.classify_status(b) == "fresh"

    def test_low_confidence_status(self):
        """Belief with confidence < 0.5 is 'low_confidence'."""
        b = self._make_belief(expires="2030-01-01", confidence=0.40)
        assert belief_parser.classify_status(b) == "low_confidence"

    def test_low_confidence_boundary(self):
        """Confidence exactly 0.5 is NOT low_confidence (boundary is exclusive)."""
        b = self._make_belief(expires="2030-01-01", confidence=0.50)
        assert belief_parser.classify_status(b) == "fresh"

    def test_expired_takes_priority_over_low_confidence(self):
        """Expired supersedes low_confidence when both conditions apply."""
        b = self._make_belief(expires="2020-01-01", confidence=0.10)
        assert belief_parser.classify_status(b) == "expired"

    def test_no_expires_no_confidence_is_fresh(self):
        """Belief with no expiry and no confidence defaults to 'fresh'."""
        b = self._make_belief()
        assert belief_parser.classify_status(b) == "fresh"

    # The two tests below cross-check status classification against fixed-date
    # fixtures at scripts/belief-parser-fixtures/. The fixtures use real calendar
    # dates that were "approaching expiry" when authored (April 2026); without
    # freezing time, those dates rot into "expired" as the test runs forward in
    # real time, producing false CI failures unrelated to parser correctness.
    # We pin today to 2026-05-01 so the fixture's expires=2026-05-15 (line 36
    # of sample-config.yml) sits at +14 days, satisfying the
    # "within 30 days" approaching_expiry contract.
    @freeze_time("2026-05-01")
    def test_sample_config_statuses(self):
        """Cross-check status classification on all sample-config.yml beliefs."""
        beliefs = belief_parser.parse_config_file(FIXTURES / "sample-config.yml")
        statuses = {b["config_key"]: b["status"] for b in beliefs}

        assert statuses["limits.wall_clock_timeout_minutes"] == "expired"
        assert statuses["limits.approaching_expiry_days"] == "approaching_expiry"
        assert statuses["limits.max_tokens"] == "low_confidence"
        assert statuses["analysis.convergence_delta"] == "fresh"

    @freeze_time("2026-05-01")
    def test_sample_agent_statuses(self):
        """Cross-check status classification on all sample-agent.md beliefs."""
        beliefs = belief_parser.parse_agent_file(FIXTURES / "sample-agent.md")
        statuses = {b["belief_id"]: b["status"] for b in beliefs}

        assert statuses["CMD-003"] == "expired"
        assert statuses["CMD-004"] == "low_confidence"
        assert statuses["CMD-005"] == "approaching_expiry"
        assert statuses["CMD-001"] == "fresh"
        assert statuses["CMD-002"] == "fresh"


# ---------------------------------------------------------------------------
# 4. Output graph structure
# ---------------------------------------------------------------------------


class TestOutputGraph:
    def _build_graph(self, config_files=None, agent_dirs=None):
        return belief_parser.build_graph(
            config_files=config_files or [],
            agent_dirs=agent_dirs or [],
        )

    def test_graph_has_required_top_level_keys(self):
        g = self._build_graph(config_files=[FIXTURES / "sample-config.yml"])
        for key in ("generated_at", "version", "beliefs", "summary"):
            assert key in g, f"missing key: {key}"

    def test_version_is_1_0_0(self):
        g = self._build_graph()
        assert g["version"] == "1.0.0"

    def test_generated_at_is_iso8601(self):
        from datetime import datetime
        g = self._build_graph()
        # Must not raise
        dt = datetime.fromisoformat(g["generated_at"])
        assert dt is not None

    def test_summary_counts_correct(self):
        g = self._build_graph(
            config_files=[FIXTURES / "sample-config.yml"],
            agent_dirs=[FIXTURES],
        )
        s = g["summary"]
        total = len(g["beliefs"])
        assert s["total"] == total
        assert s["fresh"] + s["approaching_expiry"] + s["expired"] + s["low_confidence"] == total

    def test_empty_sources_produces_zero_beliefs(self):
        g = self._build_graph(config_files=[FIXTURES / "empty-config.yml"])
        assert g["beliefs"] == []
        assert g["summary"]["total"] == 0

    def test_config_belief_has_config_key_and_value(self):
        g = self._build_graph(config_files=[FIXTURES / "sample-config.yml"])
        config_beliefs = [b for b in g["beliefs"] if b["belief_id"].startswith("config:")]
        assert len(config_beliefs) > 0
        for b in config_beliefs:
            assert "config_key" in b
            assert "config_value" in b

    def test_agent_belief_has_no_config_key(self):
        g = self._build_graph(agent_dirs=[FIXTURES])
        agent_beliefs = [b for b in g["beliefs"] if not b["belief_id"].startswith("config:")]
        # All md beliefs in fixtures dir have non-config IDs
        for b in agent_beliefs:
            assert "config_key" not in b or b.get("config_key") is None

    def test_deterministic_output(self):
        """Running twice with same input must produce identical JSON (FR-006)."""
        g1 = self._build_graph(config_files=[FIXTURES / "sample-config.yml"])
        g2 = self._build_graph(config_files=[FIXTURES / "sample-config.yml"])
        # Strip generated_at for comparison (timestamps differ by definition)
        g1.pop("generated_at")
        g2.pop("generated_at")
        assert json.dumps(g1, sort_keys=True) == json.dumps(g2, sort_keys=True)


# ---------------------------------------------------------------------------
# 5. Error handling (FR-007)
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_malformed_annotation_logs_warning_and_continues(self, capsys):
        """Malformed @belief block logs WARNING to stderr and continues parsing."""
        beliefs = belief_parser.parse_config_file(FIXTURES / "malformed-config.yml")
        captured = capsys.readouterr()
        # Must have warned
        assert "WARNING" in captured.err or "warning" in captured.err.lower()
        # Must still return beliefs from healthy annotations
        keys = [b["config_key"] for b in beliefs]
        assert "good.fine_key" in keys
        assert "also_good.recovery_key" in keys

    def test_missing_file_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            belief_parser.parse_config_file(Path("/nonexistent/path/config.yml"))

    def test_missing_agent_dir_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            belief_parser.build_graph(agent_dirs=[Path("/nonexistent/agents")])


# ---------------------------------------------------------------------------
# 6. CLI integration (subprocess)
# ---------------------------------------------------------------------------


class TestCLIIntegration:
    def test_cli_produces_valid_json(self, tmp_path):
        import subprocess

        out_file = tmp_path / "output.json"
        result = subprocess.run(
            [
                "python3",
                str(Path(__file__).parent.parent.parent / "scripts" / "belief-parser.py"),
                "--config",
                str(FIXTURES / "sample-config.yml"),
                "--agents",
                str(FIXTURES),
                "--output",
                str(out_file),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert "beliefs" in data
        assert "summary" in data

    def test_cli_empty_sources_exit_zero(self, tmp_path):
        import subprocess

        out_file = tmp_path / "output.json"
        result = subprocess.run(
            [
                "python3",
                str(Path(__file__).parent.parent.parent / "scripts" / "belief-parser.py"),
                "--config",
                str(FIXTURES / "empty-config.yml"),
                "--output",
                str(out_file),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(out_file.read_text())
        assert data["summary"]["total"] == 0
