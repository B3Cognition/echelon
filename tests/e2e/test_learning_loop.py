"""T031/T032/T034: Learning loop + prompt lint unit tests.

T031: Agent score delta emitter — cold-start + warm case
T032: Pattern detection — match existing + append new
T034: Prompt lint harness — ambiguous term detection + --root override
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.python.emit_score_deltas import (
    _apply_deltas,
    _extract_score_events,
    _update_leaderboard,
    emit_score_deltas,
)
from scripts.python.detect_patterns import (
    _collect_signals,
    _match_pattern,
    _next_pattern_id,
    detect_patterns,
)
from scripts.python.prompt_lint import lint_prompts, _load_glossary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_GLOSSARY = [
    {
        "term": "Phase",
        "senses": [
            {"sense": "coarse phase group", "detect": "in phase field", "example": "build_init"},
            {"sense": "graph node", "detect": "in definition.yaml node id", "example": "phase1-what"},
        ],
    },
    {
        "term": "Run",
        "senses": [
            {"sense": "single squad execution", "detect": "when used as noun", "example": "the current Run"},
            {"sense": "to execute", "detect": "when used as verb", "example": "run the script"},
        ],
    },
    {
        "term": "UniqueTermXYZ",
        "senses": [
            {"sense": "only sense", "detect": "always", "example": "UniqueTermXYZ"},
        ],
    },
]

SAMPLE_JOURNAL = [
    {
        "id": "RJ-001",
        "type": "agent_scores",
        "phase": "done",
        "agent": "SCOREKEEPER",
        "timestamp": "2026-04-01T10:00:00Z",
        "data": {
            "scores": [
                {"agent": "CARTOGRAPHER", "score": 4, "action": "spec_32_frs", "reason": "32 FRs produced"},
                {"agent": "SAGE", "score": 3, "action": "why_analysis", "reason": "4 passes"},
            ]
        },
    },
    {
        "id": "RJ-002",
        "type": "routing_decision",
        "phase": "phase1-what",
        "agent": "COMMANDER",
        "data": {"condition": "always", "next_phase": "phase1-what"},
    },
]

SAMPLE_JOURNAL_WITH_FAILURE = [
    {
        "id": "RJ-010",
        "type": "preflight_result",
        "phase": "preflight",
        "agent": "COMMANDER",
        "data": {
            "dependency": "skill:GOLDDIGGER",
            "status": "UNAVAILABLE",
            "reason": "skill-provisioning failure — golddigger not in tool set",
            "detected_cause": "GOLDDIGGER subagent skill not provisioned",
            "stderr_excerpt": "skill not found in subagent dispatch context",
        },
    },
    {
        "id": "RJ-011",
        "type": "issue",
        "data": {
            "message": "structure gate stalled at 0.62 across 3 iterations delta < 0.02",
            "detail": "why2 quality gate plateau, parser compatibility mismatch",
        },
    },
]

SAMPLE_PATTERNS = [
    {
        "id": "PAT-001",
        "name": "Substrate-Coherence Diagnosis for Quality Gate Plateaus",
        "domain": "spec-quality / why-gate",
        "tags": ["why2", "structure-gate", "quality-gate", "parser-compatibility"],
        "reuse_counter": 0,
        "status": "active",
    },
    {
        "id": "PAT-002",
        "name": "Cross-Cutting Off-Graph Preflight Unification",
        "domain": "workflow-reliability / dispatch",
        "tags": ["preflight", "dispatch", "off-graph", "golddigger"],
        "reuse_counter": 0,
        "status": "active",
    },
]

SAMPLE_PITFALLS = [
    {
        "id": "PIT-001",
        "name": "Leading Tag Markers Corrupt Quality Gate Entity Extraction",
        "domain": "spec-quality",
        "tags": ["why2", "structure-gate", "fr-format", "tag-placement"],
        "trigger": "FR lines prefixed with annotation tags corrupt entity extraction",
        "avoidance": "Place annotation tags at END of FR lines",
        "confidence": 0.90,
    },
]


# ---------------------------------------------------------------------------
# T031: emit_score_deltas
# ---------------------------------------------------------------------------


class TestExtractScoreEvents:
    def test_extracts_agent_scores_entries(self):
        events = _extract_score_events(SAMPLE_JOURNAL, "squad-001")
        assert len(events) == 2
        agents = {e["agent"] for e in events}
        assert "CARTOGRAPHER" in agents
        assert "SAGE" in agents

    def test_empty_journal_returns_empty_events(self):
        events = _extract_score_events([], "squad-001")
        assert events == []

    def test_routing_entries_not_extracted(self):
        events = _extract_score_events(SAMPLE_JOURNAL, "squad-001")
        agents = {e["agent"] for e in events}
        assert "COMMANDER" not in agents  # routing entry ignored

    def test_score_values_preserved(self):
        events = _extract_score_events(SAMPLE_JOURNAL, "squad-001")
        carto = next(e for e in events if e["agent"] == "CARTOGRAPHER")
        assert carto["score"] == 4


class TestApplyDeltas:
    def test_cold_start_adds_null_delta_entry(self):
        scores = {"agents": {}}
        events = [{"agent": "CARTOGRAPHER", "score": 4, "action": "spec_work", "reason": "test"}]
        updated = _apply_deltas(scores, events, "squad-001")
        history = updated["agents"]["CARTOGRAPHER"]["history"]
        null_entry = next((h for h in history if h.get("action") == "null_delta"), None)
        assert null_entry is not None
        assert null_entry["score"] is None

    def test_cold_start_followed_by_actual_score(self):
        scores = {"agents": {}}
        events = [{"agent": "SAGE", "score": 3, "action": "why_pass", "reason": "test"}]
        updated = _apply_deltas(scores, events, "squad-001")
        history = updated["agents"]["SAGE"]["history"]
        score_entry = next((h for h in history if h.get("action") != "null_delta"), None)
        assert score_entry is not None
        assert score_entry["score"] == 3

    def test_warm_case_computes_delta(self):
        """Second run: prior score exists → delta is computed."""
        scores = {
            "agents": {
                "CARTOGRAPHER": {
                    "lifetime_score": 4,
                    "current_run_score": 4,
                    "total_dispatches": 1,
                    "avg_score_per_dispatch": 4.0,
                    "badges": [],
                    "history": [
                        {"run_id": "squad-000", "score": 4, "action": "prior",
                         "reason": "", "delta": None, "badges_earned": [],
                         "failure_modes": [], "peer_appreciation": []},
                    ],
                }
            }
        }
        events = [{"agent": "CARTOGRAPHER", "score": 5, "action": "spec_improved", "reason": "better"}]
        updated = _apply_deltas(scores, events, "squad-001")
        history = updated["agents"]["CARTOGRAPHER"]["history"]
        new_entry = next(h for h in reversed(history) if h.get("run_id") == "squad-001")
        assert new_entry["delta"] == 1.0

    def test_warm_case_negative_delta(self):
        scores = {
            "agents": {
                "SAGE": {
                    "lifetime_score": 4,
                    "current_run_score": 4,
                    "total_dispatches": 1,
                    "avg_score_per_dispatch": 4.0,
                    "badges": [],
                    "history": [
                        {"run_id": "squad-000", "score": 4, "action": "prior",
                         "reason": "", "delta": None, "badges_earned": [],
                         "failure_modes": [], "peer_appreciation": []},
                    ],
                }
            }
        }
        events = [{"agent": "SAGE", "score": 2, "action": "regression", "reason": "bad run"}]
        updated = _apply_deltas(scores, events, "squad-001")
        history = updated["agents"]["SAGE"]["history"]
        new_entry = next(h for h in reversed(history) if h.get("run_id") == "squad-001")
        assert new_entry["delta"] == -2.0

    def test_null_score_produces_null_delta(self):
        scores = {"agents": {}}
        events = [{"agent": "COMMANDER", "score": None, "action": "null_delta", "reason": "no score"}]
        updated = _apply_deltas(scores, events, "squad-001")
        history = updated["agents"]["COMMANDER"]["history"]
        assert any(h.get("delta") is None for h in history)

    def test_current_run_score_updated(self):
        scores = {"agents": {}}
        events = [{"agent": "SCOUT", "score": 3, "action": "recon", "reason": ""}]
        updated = _apply_deltas(scores, events, "squad-001")
        assert updated["agents"]["SCOUT"]["current_run_score"] == 3


class TestEmitScoreDeltasE2E:
    def test_cold_start_emits_at_least_one_delta(self, tmp_path):
        run_id = "squad-test-001"
        run_dir = tmp_path / "squad" / run_id
        run_dir.mkdir(parents=True)
        kb_dir = tmp_path / "kb"
        kb_dir.mkdir()

        # Journal with score events
        journal_line = json.dumps({
            "id": "RJ-001",
            "type": "agent_scores",
            "data": {"scores": [
                {"agent": "CARTOGRAPHER", "score": 4, "action": "spec", "reason": "good"}
            ]},
        })
        (run_dir / "reasoning-journal.jsonl").write_text(journal_line, encoding="utf-8")

        report = emit_score_deltas(
            run_id=run_id,
            squad_dir=tmp_path / "squad",
            kb_dir=kb_dir,
            dry_run=True,
        )
        assert report["deltas_emitted"] >= 1
        assert "CARTOGRAPHER" in report["agents_updated"]

    def test_warm_case_emits_delta_for_existing_agent(self, tmp_path):
        run_id = "squad-test-002"
        run_dir = tmp_path / "squad" / run_id
        run_dir.mkdir(parents=True)
        kb_dir = tmp_path / "kb"
        kb_dir.mkdir()

        # Pre-populate agent-scores.yaml with prior data
        prior_scores = {
            "schema_version": 1,
            "meta": {"cold_start": False, "total_runs": 1, "last_updated": "2026-04-01"},
            "leaderboard": [],
            "agents": {
                "SAGE": {
                    "lifetime_score": 3,
                    "current_run_score": 3,
                    "total_dispatches": 1,
                    "avg_score_per_dispatch": 3.0,
                    "badges": [],
                    "history": [
                        {"run_id": "squad-000", "score": 3, "action": "prior",
                         "reason": "", "delta": None, "badges_earned": [],
                         "failure_modes": [], "peer_appreciation": []},
                    ],
                }
            },
            "runs": [],
        }
        try:
            import yaml
            (kb_dir / "agent-scores.yaml").write_text(
                yaml.dump(prior_scores, default_flow_style=False),
                encoding="utf-8",
            )
        except ImportError:
            (kb_dir / "agent-scores.yaml").write_text(
                json.dumps(prior_scores, indent=2), encoding="utf-8"
            )

        journal_line = json.dumps({
            "id": "RJ-001",
            "type": "agent_scores",
            "data": {"scores": [
                {"agent": "SAGE", "score": 4, "action": "improved", "reason": "better"}
            ]},
        })
        (run_dir / "reasoning-journal.jsonl").write_text(journal_line, encoding="utf-8")

        report = emit_score_deltas(
            run_id=run_id,
            squad_dir=tmp_path / "squad",
            kb_dir=kb_dir,
            dry_run=True,
        )
        assert report["deltas_emitted"] >= 1

    def test_missing_run_dir_returns_error(self, tmp_path):
        report = emit_score_deltas(
            run_id="squad-nonexistent",
            squad_dir=tmp_path / "squad",
            kb_dir=tmp_path / "kb",
            dry_run=True,
        )
        assert "error" in report

    def test_empty_journal_emits_null_delta(self, tmp_path):
        run_id = "squad-empty-001"
        run_dir = tmp_path / "squad" / run_id
        run_dir.mkdir(parents=True)
        kb_dir = tmp_path / "kb"
        kb_dir.mkdir()
        (run_dir / "reasoning-journal.jsonl").write_text("", encoding="utf-8")
        (run_dir / "state.json").write_text(
            json.dumps({"status": "done", "run_id": run_id}), encoding="utf-8"
        )

        report = emit_score_deltas(
            run_id=run_id,
            squad_dir=tmp_path / "squad",
            kb_dir=kb_dir,
            dry_run=True,
        )
        # Contract: at least 1 delta emitted (null_delta for empty journal)
        assert report["deltas_emitted"] >= 1


# ---------------------------------------------------------------------------
# T032: detect_patterns
# ---------------------------------------------------------------------------


class TestCollectSignals:
    def test_extracts_reason_from_journal(self):
        journal = [
            {"id": "RJ-1", "type": "issue", "data": {"reason": "quality gate stalled"}},
        ]
        signals = _collect_signals(journal, [])
        assert any("quality gate stalled" in s["text"] for s in signals)

    def test_extracts_from_issues_log(self):
        issues = [{"id": "I-001", "message": "structure score below threshold"}]
        signals = _collect_signals([], issues)
        assert any("structure score" in s["text"] for s in signals)

    def test_empty_inputs_produce_empty_signals(self):
        assert _collect_signals([], []) == []


class TestMatchPattern:
    def test_tag_overlap_matches(self):
        pattern = {"name": "Test", "tags": ["why2", "quality-gate"]}
        signals = [{"text": "why2 quality gate failure detected", "source": "test"}]
        assert _match_pattern(pattern, signals) is True

    def test_no_overlap_no_match(self):
        pattern = {"name": "Unrelated Pattern", "tags": ["alpha", "beta"]}
        signals = [{"text": "completely different content here", "source": "test"}]
        assert _match_pattern(pattern, signals) is False

    def test_empty_signals_no_match(self):
        pattern = {"name": "Test Pattern", "tags": ["why2"]}
        assert _match_pattern(pattern, []) is False


class TestNextPatternId:
    def test_first_id_is_pat_001(self):
        assert _next_pattern_id([]) == "PAT-001"

    def test_increments_from_existing(self):
        existing = [{"id": "PAT-001"}, {"id": "PAT-002"}]
        assert _next_pattern_id(existing) == "PAT-003"

    def test_handles_gaps(self):
        existing = [{"id": "PAT-001"}, {"id": "PAT-005"}]
        assert _next_pattern_id(existing) == "PAT-006"


class TestDetectPatternsE2E:
    def _make_run(self, tmp_path, run_id, journal=None, state=None):
        run_dir = tmp_path / "squad" / run_id
        run_dir.mkdir(parents=True)
        journal_text = "\n".join(json.dumps(e) for e in (journal or []))
        (run_dir / "reasoning-journal.jsonl").write_text(journal_text, encoding="utf-8")
        if state:
            (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
        return run_dir

    def _make_kb(self, tmp_path, patterns=None, pitfalls=None):
        kb_dir = tmp_path / "kb"
        kb_dir.mkdir(exist_ok=True)
        try:
            import yaml

            if patterns is not None:
                (kb_dir / "patterns.yaml").write_text(
                    yaml.dump(patterns, default_flow_style=False),
                    encoding="utf-8",
                )
            if pitfalls is not None:
                (kb_dir / "pitfalls.yaml").write_text(
                    yaml.dump(pitfalls, default_flow_style=False),
                    encoding="utf-8",
                )
        except ImportError:
            if patterns is not None:
                (kb_dir / "patterns.yaml").write_text(
                    json.dumps(patterns, indent=2), encoding="utf-8"
                )
            if pitfalls is not None:
                (kb_dir / "pitfalls.yaml").write_text(
                    json.dumps(pitfalls, indent=2), encoding="utf-8"
                )
        return kb_dir

    def test_matches_existing_pattern_and_increments_counter(self, tmp_path):
        self._make_run(
            tmp_path, "squad-001",
            journal=SAMPLE_JOURNAL_WITH_FAILURE,
        )
        kb_dir = self._make_kb(tmp_path, patterns=[p.copy() for p in SAMPLE_PATTERNS])

        report = detect_patterns("squad-001", tmp_path / "squad", kb_dir, dry_run=True)

        # Should match PAT-002 (preflight/golddigger tags)
        assert report["reuse_counters_incremented"] >= 1
        assert "PAT-002" in report["patterns_matched"]

    def test_no_match_produces_zero_increments(self, tmp_path):
        self._make_run(
            tmp_path, "squad-quiet",
            journal=[{"id": "RJ-001", "type": "routing_decision", "data": {}}],
        )
        kb_dir = self._make_kb(tmp_path, patterns=[p.copy() for p in SAMPLE_PATTERNS])

        report = detect_patterns("squad-quiet", tmp_path / "squad", kb_dir, dry_run=True)
        assert report["reuse_counters_incremented"] == 0

    def test_missing_run_returns_error(self, tmp_path):
        kb_dir = self._make_kb(tmp_path, patterns=[])
        report = detect_patterns("squad-missing", tmp_path / "squad", kb_dir, dry_run=True)
        assert "error" in report

    def test_dry_run_does_not_write_file(self, tmp_path):
        self._make_run(
            tmp_path, "squad-001",
            journal=SAMPLE_JOURNAL_WITH_FAILURE,
        )
        kb_dir = self._make_kb(tmp_path, patterns=[p.copy() for p in SAMPLE_PATTERNS])

        patterns_path = kb_dir / "patterns.yaml"
        mtime_before = patterns_path.stat().st_mtime if patterns_path.exists() else None

        detect_patterns("squad-001", tmp_path / "squad", kb_dir, dry_run=True)

        if patterns_path.exists() and mtime_before is not None:
            mtime_after = patterns_path.stat().st_mtime
            # dry_run should not have modified the file
            assert mtime_after == mtime_before


# ---------------------------------------------------------------------------
# T034: prompt_lint
# ---------------------------------------------------------------------------


FIXTURES_PROMPTS = REPO_ROOT / "tests" / "fixtures" / "prompts"
DEFINITION_PATH = REPO_ROOT / "extension" / "workflow" / "definition.yaml"


class TestPromptLintCLI:
    def test_root_override_scans_fixture_dir(self):
        """CLI --root override: fixture dir with ambiguous_prompt.md must detect ambiguous terms."""
        result = lint_prompts(FIXTURES_PROMPTS, DEFINITION_PATH)
        # Should find ambiguous terms in ambiguous_prompt.md
        assert result["files_scanned"] >= 1
        assert result["terms_loaded"] >= 1

    def test_ambiguous_prompt_detected(self):
        result = lint_prompts(FIXTURES_PROMPTS, DEFINITION_PATH)
        assert result["ambiguous_count"] > 0
        assert result["exit_code"] == 1

    def test_ambiguous_files_includes_ambiguous_prompt(self):
        result = lint_prompts(FIXTURES_PROMPTS, DEFINITION_PATH)
        assert any("ambiguous_prompt" in f for f in result["ambiguous_files"])

    def test_findings_have_line_numbers(self):
        result = lint_prompts(FIXTURES_PROMPTS, DEFINITION_PATH)
        for finding in result["findings"]:
            assert "line_number" in finding
            assert finding["line_number"] >= 1

    def test_missing_root_returns_error(self, tmp_path):
        result = lint_prompts(tmp_path / "nonexistent_dir", DEFINITION_PATH)
        assert result.get("exit_code") == 2 or "error" in result

    def test_clean_prompt_does_not_trigger_exit_one(self, tmp_path):
        """A directory with only the clean prompt should yield exit_code=0."""
        # Copy clean prompt to isolated directory
        clean_dir = tmp_path / "clean"
        clean_dir.mkdir()
        (clean_dir / "clean.md").write_text(
            "# Clean Agent\n\nThis agent does not use any ambiguous terms.\n",
            encoding="utf-8",
        )

        result = lint_prompts(clean_dir, DEFINITION_PATH)
        if result.get("terms_loaded", 0) > 0:
            # If definition loaded, check result
            assert result["exit_code"] == 0 or result["ambiguous_count"] == 0

    def test_glossary_loads_all_terms(self):
        glossary = _load_glossary(DEFINITION_PATH)
        assert len(glossary) >= 8

    def test_all_glossary_terms_have_senses(self):
        glossary = _load_glossary(DEFINITION_PATH)
        for term_entry in glossary:
            assert len(term_entry.get("senses", [])) >= 1

    def test_report_has_required_keys(self):
        result = lint_prompts(FIXTURES_PROMPTS, DEFINITION_PATH)
        required = ["files_scanned", "terms_loaded", "findings",
                    "ambiguous_count", "ambiguous_files", "exit_code"]
        for k in required:
            assert k in result, f"Missing key: {k}"
