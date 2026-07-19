"""Unit tests for scripts/sue_reproducibility.py (SUE v3).

Design: docs/superpowers/specs/2026-07-19-sue-v3-reproducibility-design.md
Offline throughout via counter-based replay stubs.
"""
from __future__ import annotations

import importlib.util
import json
import shlex
import stat
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v3 = _load("sue_reproducibility")
v1 = v3.v1


def _edge(s, t, etype="performs", line=1):
    return v3.Edge(s=s, type=etype, t=t, line=line, conf=0.9)


def _interp(edges=(), assumptions=(), assertions=()):
    return v3.ReqInterpretation(
        edges=list(edges), assumptions=list(assumptions), assertions=list(assertions)
    )


def _reader(no, reqs, framing="structural", ungrounded=0):
    return v3.ReaderGraph(
        reader_no=no, framing=framing, requirements=reqs, ungrounded_edges=ungrounded
    )


class TestModelCommands:
    def test_explicit_copilot_provider_spec(self):
        command = v3.parse_model_command("copilot=copilot --no-color")
        assert command.provider == "copilot"
        assert command.command == "copilot --no-color"
        assert command.model_tag == "copilot"

    def test_legacy_claude_command_is_inferred(self):
        command = v3.parse_model_command("claude --model sonnet")
        assert command.provider == "claude"
        assert command.command == "claude --model sonnet"

    def test_unknown_stub_keeps_legacy_claude_protocol(self):
        command = v3.parse_model_command("/tmp/replay-stub")
        assert command.provider == "claude"

    def test_copilot_command_rejects_embedded_prompt_flag(self):
        with pytest.raises(v1.ArgumentFailure, match="without -p"):
            v3.parse_model_command("copilot=copilot -p")

    def test_malformed_legacy_command_uses_argument_failure(self):
        with pytest.raises(v1.ArgumentFailure, match="shell-parseable"):
            v3.parse_model_command('stub "unterminated')


class TestReaderJobs:
    def test_two_models_receive_the_same_three_framings(self):
        commands = [
            v3.ModelCommand("claude", "claude", "claude"),
            v3.ModelCommand("copilot", "copilot", "copilot"),
        ]
        jobs = v3.build_reader_jobs(commands, 3, v3.FRAMINGS)
        assert [
            (job.model_command.provider, job.framing_name)
            for job in jobs
        ] == [
            ("claude", "structural"),
            ("claude", "behavioural"),
            ("claude", "adversarial"),
            ("copilot", "structural"),
            ("copilot", "behavioural"),
            ("copilot", "adversarial"),
        ]
        assert [job.reader_no for job in jobs] == list(range(1, 7))

    def test_sidecar_keeps_provider_model_and_framing_separate(self):
        reader = v3.ReaderGraph(
            reader_no=1,
            framing="structural",
            provider="copilot",
            model_tag="copilot",
            requirements={},
            ungrounded_edges=0,
        )
        sidecar = v3.build_sidecar(
            Path("spec.md"), [reader], {}, 1.0, [], {}, "2026-07-19"
        )
        encoded = sidecar["readers"][0]
        assert encoded["provider"] == "copilot"
        assert encoded["model_tag"] == "copilot"
        assert encoded["framing"] == "structural"


class TestNorm:
    def test_articles_case_plural(self):
        assert v3.norm("The Builders") == "builder"
        assert v3.norm("an  inline   error") == "inline error"

    def test_preserves_short_and_ss_words(self):
        assert v3.norm("status") == "status"
        assert v3.norm("process") == "process"


class TestScanIds:
    def test_finds_mixed_id_families(self):
        spec = v1.SpecDocument(path=Path("x"), lines=[
            "- **FR-001**: ...", "AC-012 and NFR-004 apply", "no ids here",
        ])
        assert v3.scan_requirement_ids(spec) == {"FR-001", "AC-012", "NFR-004"}

    def test_non_behavioural_families_excluded_by_default(self):
        spec = v1.SpecDocument(path=Path("x"), lines=[
            "FR-001 holds; assumption A-003 and open question OQ-002 and U-007",
        ])
        assert v3.scan_requirement_ids(spec) == {"FR-001"}

    def test_families_opt_in(self):
        spec = v1.SpecDocument(path=Path("x"), lines=["FR-001 and A-003"])
        assert v3.scan_requirement_ids(spec, ("FR", "A")) == {"FR-001", "A-003"}


class TestLabelGrounding:
    LINE = "the system MUST display an inline error and retain the last valid card rendering."

    def test_spec_words_accepted(self):
        assert v3._label_grounded("display inline error", self.LINE)
        assert v3._label_grounded("The System", self.LINE)

    def test_paraphrase_rejected(self):
        assert not v3._label_grounded("show validation message", self.LINE)

    def test_trailing_punctuation_cannot_shield_singularization(self):
        # Live regression: "commands," in the line vs "commands" in the label
        # must compare equal after normalization (order-of-operations bug).
        line = "run changes occur only through sanctioned commands, leaving state alone"
        assert v3._label_grounded("sanctioned commands", line)
        assert v3._label_grounded("sanctioned command", line)

    def test_validate_graph_enforces_anchor(self):
        lines = ["- **FR-001**: the system MUST write the report."]
        result = v3.validate_graph(
            {"requirements": {"FR-001": {"edges": [
                {"s": "system", "type": "performs", "t": "generate output",
                 "line": 1, "conf": 0.9}]}}},
            {"FR-001"}, 1, spec_lines=lines,
        )
        assert isinstance(result, v1.ParseFailure)
        assert "must reuse the specification's own words" in result.reason

    def test_validate_graph_accepts_anchored_labels(self):
        lines = ["- **FR-001**: the system MUST write the report."]
        result = v3.validate_graph(
            {"requirements": {"FR-001": {"edges": [
                {"s": "system", "type": "performs", "t": "write report",
                 "line": 1, "conf": 0.9}]}}},
            {"FR-001"}, 1, spec_lines=lines,
        )
        reqs, ungrounded = result
        assert len(reqs["FR-001"].edges) == 1 and ungrounded == 0


class TestScoring:
    def test_identical_graphs_score_1(self):
        reqs = {"FR-001": _interp([_edge("system", "write report")])}
        per = v3.score_requirements([_reader(1, reqs), _reader(2, reqs)])
        assert per["FR-001"]["score"] == 1.0
        assert v3.overall_score(per) == 1.0

    def test_disjoint_graphs_score_0(self):
        a = {"FR-001": _interp([_edge("system", "write report")])}
        b = {"FR-001": _interp([_edge("operator", "delete report")])}
        per = v3.score_requirements([_reader(1, a), _reader(2, b)])
        assert per["FR-001"]["score"] == 0.0

    def test_both_empty_requirement_scores_1(self):
        a = {"FR-001": _interp()}
        b = {"FR-001": _interp()}
        per = v3.score_requirements([_reader(1, a), _reader(2, b)])
        assert per["FR-001"]["score"] == 1.0

    def test_normalization_bridges_wording(self):
        a = {"FR-001": _interp([_edge("The system", "the reports")])}
        b = {"FR-001": _interp([_edge("system", "report")])}
        per = v3.score_requirements([_reader(1, a), _reader(2, b)])
        assert per["FR-001"]["score"] == 1.0

    def test_near_miss_counted(self):
        a = {"FR-001": _interp([_edge("system", "write report")])}
        b = {"FR-001": _interp([_edge("system", "write summary")])}
        per = v3.score_requirements([_reader(1, a), _reader(2, b)])
        assert per["FR-001"]["score"] == 0.0
        assert per["FR-001"]["near_misses"] == 1

    def test_missing_reader_treated_as_empty(self):
        a = {"FR-001": _interp([_edge("system", "write report")])}
        per = v3.score_requirements([_reader(1, a), _reader(2, {})])
        assert per["FR-001"]["score"] == 0.0
        assert per["FR-001"]["readers_covering"] == 1


class TestWitnesses:
    def _assertion(self, then, lines=(3,)):
        return v3.Assertion(given="a valid rule", when="the builder saves",
                            then=then, lines=list(lines))

    def test_conflicting_then_yields_witness(self):
        a = {"FR-001": _interp(assertions=[self._assertion("the file persists")])}
        b = {"FR-001": _interp(assertions=[self._assertion("the save is blocked")])}
        witnesses, variants = v3.find_witnesses([_reader(1, a), _reader(2, b)])
        assert len(witnesses) == 1 and variants == 0
        assert witnesses[0].req_id == "FR-001"

    def test_agreeing_then_no_witness(self):
        a = {"FR-001": _interp(assertions=[self._assertion("The File Persists")])}
        b = {"FR-001": _interp(assertions=[self._assertion("the file persists")])}
        assert v3.find_witnesses([_reader(1, a), _reader(2, b)]) == ([], 0)

    def test_phrasing_variant_is_not_a_witness(self):
        """Live regression (W1): same meaning restated must count as a
        phrasing variant, never a witness candidate."""
        a = {"FR-001": _interp(assertions=[self._assertion(
            "two model calls occur and the report lands beside the specification")])}
        b = {"FR-001": _interp(assertions=[self._assertion(
            "exactly 2 model calls occur and the report lands in the specification directory")])}
        witnesses, variants = v3.find_witnesses([_reader(1, a), _reader(2, b)])
        assert witnesses == [] and variants == 1

    def test_ungrounded_side_cannot_witness(self):
        a = {"FR-001": _interp(assertions=[self._assertion("the file persists")])}
        b = {"FR-001": _interp(assertions=[self._assertion("the save is blocked", lines=())])}
        assert v3.find_witnesses([_reader(1, a), _reader(2, b)]) == ([], 0)

    def test_different_situations_no_witness(self):
        a = {"FR-001": _interp(assertions=[v3.Assertion(
            given="a valid rule", when="save", then="persists", lines=[3])])}
        b = {"FR-001": _interp(assertions=[v3.Assertion(
            given="an invalid rule", when="save", then="blocked", lines=[4])])}
        assert v3.find_witnesses([_reader(1, a), _reader(2, b)]) == ([], 0)


class TestEvidenceMetrics:
    def test_identical_citations_have_full_overlap_and_coverage(self):
        reqs = {"FR-001": _interp([_edge("system", "write report", line=1)])}
        metrics = v3.evidence_metrics([_reader(1, reqs), _reader(2, reqs)])
        assert metrics["mean_overlap"] == 1.0
        assert metrics["coverage"] == 1.0
        assert metrics["per_requirement"]["FR-001"]["overlap"] == 1.0

    def test_disjoint_citations_have_zero_overlap(self):
        a = {"FR-001": _interp([_edge("system", "write report", line=1)])}
        b = {"FR-001": _interp([_edge("system", "write report", line=2)])}
        metrics = v3.evidence_metrics([_reader(1, a), _reader(2, b)])
        assert metrics["mean_overlap"] == 0.0
        assert metrics["coverage"] == 1.0

    def test_no_evidence_is_na_not_perfect_overlap(self):
        reqs = {"FR-001": _interp()}
        metrics = v3.evidence_metrics([_reader(1, reqs), _reader(2, reqs)])
        assert metrics["mean_overlap"] is None
        assert metrics["coverage"] == 0.0
        assert metrics["per_requirement"]["FR-001"]["overlap"] is None

    def test_evidence_is_compared_per_requirement(self):
        left = {
            "FR-001": _interp([_edge("system", "write report", line=1)]),
            "FR-002": _interp([_edge("system", "read report", line=2)]),
        }
        right = {
            "FR-001": _interp([_edge("system", "write report", line=1)]),
            "FR-002": _interp([_edge("system", "read report", line=3)]),
        }
        metrics = v3.evidence_metrics([_reader(1, left), _reader(2, right)])
        assert metrics["per_requirement"]["FR-001"]["overlap"] == 1.0
        assert metrics["per_requirement"]["FR-002"]["overlap"] == 0.0
        assert metrics["mean_overlap"] == 0.5

    def test_missing_reader_evidence_reduces_reader_coverage(self):
        reqs = {"FR-001": _interp([_edge("system", "write report", line=1)])}
        metrics = v3.evidence_metrics(
            [_reader(1, reqs), _reader(2, reqs), _reader(3, {})]
        )
        requirement = metrics["per_requirement"]["FR-001"]
        assert requirement["overlap"] == 0.0
        assert requirement["reader_coverage"] == pytest.approx(2 / 3)

    def test_negation_asymmetric_witness_kind(self):
        a = {"FR-001": _interp(assertions=[v3.Assertion(
            given="a rule", when="save", then="the file persists", lines=[3])])}
        b = {"FR-001": _interp(assertions=[v3.Assertion(
            given="a rule", when="save", then="the write is rejected", lines=[3])])}
        witnesses, _ = v3.find_witnesses([_reader(1, a), _reader(2, b)])
        assert witnesses[0].kind == "negation-asymmetric"

    def test_negation_asymmetry_does_not_claim_semantic_opposition(self):
        a = {"FR-001": _interp(assertions=[v3.Assertion(
            given="a rule", when="save", then="the file persists", lines=[3])])}
        b = {"FR-001": _interp(assertions=[v3.Assertion(
            given="a rule", when="save",
            then="the file not only persists but is replicated", lines=[3])])}
        witnesses, _ = v3.find_witnesses([_reader(1, a), _reader(2, b)])
        assert witnesses[0].kind == "negation-asymmetric"


class TestThinConsensus:
    def test_high_agreement_over_thin_content_flagged(self):
        reqs = {"FR-001": _interp([_edge("system", "write report")])}
        per = v3.score_requirements([_reader(1, reqs), _reader(2, reqs)])
        assert per["FR-001"]["thin_consensus"] is True

    def test_rich_agreement_not_flagged(self):
        rich = _interp([_edge("system", "write report"),
                        _edge("system", "print summary", line=2),
                        _edge("operator", "run script", line=3)])
        per = v3.score_requirements([_reader(1, {"FR-001": rich}),
                                     _reader(2, {"FR-001": rich})])
        assert per["FR-001"]["thin_consensus"] is False


class TestFractureLines:
    def test_divergent_edges_attribute_their_lines(self):
        a = {"FR-001": _interp([_edge("system", "write report", line=7)])}
        b = {"FR-001": _interp([_edge("operator", "delete report", line=9)])}
        readers = [_reader(1, a), _reader(2, b)]
        per = v3.score_requirements(readers)
        fractures = v3.fracture_lines(readers, per, [])
        ranked = dict(fractures["FR-001"])
        assert ranked == {7: 1, 9: 1}

    def test_shared_edges_not_attributed(self):
        shared = {"FR-001": _interp([_edge("system", "write report", line=7)])}
        readers = [_reader(1, shared), _reader(2, shared)]
        per = v3.score_requirements(readers)
        assert v3.fracture_lines(readers, per, []) == {}


class TestChunking:
    def test_small_set_single_chunk(self):
        ids = {f"FR-{i:03d}" for i in range(1, 6)}
        assert v3.chunk_ids(ids) == [ids]

    def test_large_set_deterministic_slices(self):
        ids = {f"FR-{i:03d}" for i in range(1, 46)}
        chunks = v3.chunk_ids(ids, size=20)
        assert [len(c) for c in chunks] == [20, 20, 5]
        assert chunks[0] == set(sorted(ids)[:20])
        rejoined = set()
        for chunk in chunks:
            rejoined |= chunk
        assert rejoined == ids


class TestValidateGraph:
    def test_unknown_requirement_id_rejected(self):
        result = v3.validate_graph(
            {"requirements": {"FR-999": {"edges": []}}}, {"FR-001"}, 10
        )
        assert isinstance(result, v1.ParseFailure)
        assert "unknown requirement id" in result.reason

    def test_bad_edge_type_rejected(self):
        result = v3.validate_graph(
            {"requirements": {"FR-001": {"edges": [
                {"s": "a", "type": "loves", "t": "b", "line": 1}]}}},
            {"FR-001"}, 10,
        )
        assert isinstance(result, v1.ParseFailure)

    def test_out_of_range_edge_dropped_and_counted(self):
        result = v3.validate_graph(
            {"requirements": {"FR-001": {"edges": [
                {"s": "a", "type": "performs", "t": "b", "line": 99},
                {"s": "a", "type": "performs", "t": "c", "line": 2}]}}},
            {"FR-001"}, 10,
        )
        reqs, ungrounded = result
        assert ungrounded == 1
        assert len(reqs["FR-001"].edges) == 1


# ── Scenario tests ───────────────────────────────────────────────────────────


_SPEC = "\n".join([
    "- **FR-001**: the system MUST write the report.",
    "- **FR-002**: the builder MUST be able to save the rule.",
])


def _graph_json(then_fr2="the save persists"):
    return json.dumps({"requirements": {
        "FR-001": {
            "edges": [{"s": "system", "type": "performs", "t": "write report",
                       "line": 1, "conf": 0.9}],
            "assumptions": [],
            "assertions": [],
        },
        "FR-002": {
            "edges": [{"s": "builder", "type": "performs", "t": "save rule",
                       "line": 2, "conf": 0.9}],
            "assumptions": [{"text": "a rule is open", "line": 2}],
            "assertions": [{"given": "an open rule", "when": "the builder saves",
                            "then": then_fr2, "lines": [2]}],
        },
    }})


def _replay_stub(tmp_path: Path, responses: list[str]) -> str:
    payload_dir = tmp_path / "replay"
    payload_dir.mkdir()
    for index, response in enumerate(responses):
        (payload_dir / f"{index}.json").write_text(response)
    counter = payload_dir / "count"
    counter.write_text("0")
    stub = tmp_path / "stub.sh"
    stub.write_text(
        "#!/bin/sh\ncat > /dev/null\n"
        f'N=$(cat "{counter}")\necho $((N + 1)) > "{counter}"\n'
        f'cat "{payload_dir}/$N.json"\n'
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return str(stub)


class TestScenario:
    def test_identical_readers_sr_1_no_witnesses(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        stub = _replay_stub(tmp_path, [_graph_json()] * 3)
        rc = v3.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Semantic reproducibility: 1.000" in out
        sidecar = json.loads((tmp_path / "semantic-reproducibility.json").read_text())
        assert sidecar["semantic_reproducibility"] == 1.0
        assert sidecar["witnesses"] == []

    def test_conflicting_assertion_yields_witness_and_fracture(self, tmp_path):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        stub = _replay_stub(tmp_path, [
            _graph_json("the save persists"),
            _graph_json("the save is blocked until review"),
            _graph_json("the save persists"),
        ])
        rc = v3.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        report = (tmp_path / "semantic-reproducibility.md").read_text()
        assert "Divergence witness candidates" in report
        assert "W1. [negation-asymmetric] FR-002" in report
        assert "evidence overlap (mean/requirement)" in report
        assert "evidence coverage" in report
        assert "the save is blocked until review" in report
        sidecar = json.loads((tmp_path / "semantic-reproducibility.json").read_text())
        assert len(sidecar["witnesses"]) == 1
        assert "evidence" in sidecar
        assert "shared_evidence" not in sidecar
        assert "FR-002" in sidecar["fracture_lines"]

    def test_reader_dropout_degrades(self, tmp_path):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        stub = _replay_stub(tmp_path, [
            _graph_json(), "garbage", "garbage", _graph_json(),
        ])
        rc = v3.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        report = (tmp_path / "semantic-reproducibility.md").read_text()
        assert "1 dropped: R2(behavioural)" in report

    def test_two_dropouts_exit_3(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        stub = _replay_stub(tmp_path, [
            _graph_json(), "garbage", "garbage", "garbage", "garbage",
        ])
        rc = v3.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 3
        assert "fewer than 2 readers" in capsys.readouterr().err

    def test_chunked_extraction_merges_per_reader(self, tmp_path, monkeypatch):
        """CHUNK_SIZE=1 forces 2 chunks per reader; merged graphs must cover
        both units and score as one interpretation."""
        monkeypatch.setattr(v3, "CHUNK_SIZE", 1)
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")

        def _chunk_json(req_only):
            full = json.loads(_graph_json())
            return json.dumps(
                {"requirements": {req_only: full["requirements"][req_only]}}
            )

        per_reader = [_chunk_json("FR-001"), _chunk_json("FR-002")]
        stub = _replay_stub(tmp_path, per_reader * 3)
        rc = v3.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        sidecar = json.loads((tmp_path / "semantic-reproducibility.json").read_text())
        assert sidecar["semantic_reproducibility"] == 1.0
        for reader in sidecar["readers"]:
            assert set(reader["requirements"]) == {"FR-001", "FR-002"}

    def test_failed_chunk_degrades_not_kills(self, tmp_path, monkeypatch):
        """One chunk failing both attempts costs coverage, not the reader —
        only a majority of failed chunks drops the reader."""
        monkeypatch.setattr(v3, "CHUNK_SIZE", 1)
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")

        def _chunk_json(req_only):
            full = json.loads(_graph_json())
            return json.dumps(
                {"requirements": {req_only: full["requirements"][req_only]}}
            )

        responses = (
            [_chunk_json("FR-001"), "garbage", "garbage"]      # R1: FR-002 chunk dies
            + [_chunk_json("FR-001"), _chunk_json("FR-002")]   # R2 full
            + [_chunk_json("FR-001"), _chunk_json("FR-002")]   # R3 full
        )
        stub = _replay_stub(tmp_path, responses)
        rc = v3.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        report = (tmp_path / "semantic-reproducibility.md").read_text()
        assert "Failed extraction chunks (coverage gaps):** R1=1" in report
        assert "3 completed" in report

    def test_no_requirement_ids_exit_1(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text("just prose with no identifiers\n")
        stub = _replay_stub(tmp_path, [])
        rc = v3.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 1
        assert "no recognizable requirement ids" in capsys.readouterr().err

    def test_empty_spec_exit_1(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text("  \n\n")
        stub = _replay_stub(tmp_path, [])
        rc = v3.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 1
        capsys.readouterr()

    def test_report_collision_exit_1(self, tmp_path, capsys):
        spec = tmp_path / "semantic-reproducibility.md"
        spec.write_text("FR-001 previous report\n")
        stub = _replay_stub(tmp_path, [])
        rc = v3.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 1
        assert spec.read_text() == "FR-001 previous report\n"
        capsys.readouterr()
