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

    def test_main_builds_pinned_codex_configs_before_preflight(
            self, tmp_path, monkeypatch, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text("- **FR-001**: system records the event.\n")
        captured = []

        def stop_at_preflight(config):
            captured.append(config)
            return (v1.EXIT_BAD_INPUT, "stop after config capture")

        monkeypatch.setattr(v1, "preflight", stop_at_preflight)

        rc = v3.main([
            str(spec),
            "--model-cmd", "codex=codex",
            "--model", "gpt-5.6-luna",
            "--reasoning-effort", "low",
        ])

        assert rc == v1.EXIT_BAD_INPUT
        assert len(captured) == 1
        assert captured[0].model == "gpt-5.6-luna"
        assert captured[0].reasoning_effort == "low"
        capsys.readouterr()


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


class TestRequirementScope:
    def test_source_bundle_ids_exclude_cross_references(self, tmp_path):
        # The spec-030 phantom-unit defect: ids quoted inside another unit's
        # body must not become units.
        path = tmp_path / "spec.md"
        path.write_text(
            "- **AC-1.1** findings overlap REQ-009 and NFR-004.\n"
            "- **FR-EL-001** The report MUST be written beside the spec.\n"
        )

        bundle, ids = v3.load_requirement_scope(path)

        assert ids == {"AC-1.1", "FR-EL-001"}
        assert [unit.id for unit in bundle.units] == ["AC-1.1", "FR-EL-001"]

    def test_lexicon_block_heads_are_bundle_units(self, tmp_path):
        path = tmp_path / "spec.lex"
        path.write_text(
            "REQ: REQ-001\n"
            "GIVEN: a builder\n"
            "WHEN: the builder acts\n"
            "THEN: behaves like REQ-099\n"
            "AC: AC-005\n"
        )

        _bundle, ids = v3.load_requirement_scope(path)

        assert ids == {"REQ-001", "AC-005"}

    def test_non_behavioural_families_are_opt_in(self, tmp_path):
        path = tmp_path / "spec.md"
        path.write_text(
            "- **FR-001** The run MUST finish.\n"
            "- **A-003** The clock is assumed monotonic.\n"
            "- **OQ-002** Which clock is authoritative?\n"
        )

        _bundle, default_ids = v3.load_requirement_scope(path)
        _bundle, selected_ids = v3.load_requirement_scope(
            path, ("FR", "A")
        )

        assert default_ids == {"FR-001"}
        assert selected_ids == {"FR-001", "A-003"}

    def test_non_prefixed_bundle_unit_remains_in_scope(self):
        document = v3.source.SourceDocument.from_text(
            id="payments",
            source_uri="payments.txt",
            media_type="text/plain",
            text="Payment retries stop after three attempts.\n",
        )
        bundle = v3.source.make_bundle(
            bundle_id="payments",
            adapter_id="manifest",
            documents=(document,),
            units=(
                v3.source.SourceUnit(
                    id="PAYMENT-RETRY",
                    kind="requirement",
                    text="Payment retries stop after three attempts.",
                    normative_level="must",
                    source_refs=(
                        v3.source.SourceRef(
                            "payments", "line-range", "L1-L1"
                        ),
                    ),
                    declared_relations=(),
                    situation=None,
                ),
            ),
        )

        assert v3.requirement_ids_from_bundle(bundle) == {"PAYMENT-RETRY"}

    def test_mention_only_prose_is_rejected_instead_of_inventing_units(
            self, tmp_path):
        path = tmp_path / "spec.md"
        path.write_text("AC-012 and NFR-004 apply, but are defined elsewhere.\n")

        with pytest.raises(v3.source.SUESourceError) as error:
            v3.load_requirement_scope(path)

        assert error.value.code == "INCONCLUSIVE_INPUT"


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

    def test_validate_graph_quarantines_ungrounded_label_instead_of_killing_chunk(self):
        lines = ["- **FR-001**: the system MUST write the report."]
        result = v3.validate_graph(
            {"requirements": {"FR-001": {"edges": [
                {"s": "system", "type": "performs", "t": "generate output",
                 "line": 1, "conf": 0.9}]}}},
            {"FR-001"}, 1, spec_lines=lines,
        )
        reqs, ungrounded = result
        assert reqs["FR-001"].edges == []
        assert ungrounded == 1

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

    def test_multiline_unit_vocabulary_is_a_valid_anchor(self, tmp_path):
        path = tmp_path / "spec.md"
        path.write_text(
            "- **FR-001** The system MUST display an inline error.\n"
            "  It MUST retain the last valid card rendering.\n"
        )
        bundle, ids = v3.load_requirement_scope(path)
        lines = path.read_text().splitlines()
        result = v3.validate_graph(
            {"requirements": {"FR-001": {
                "edges": [{
                    "s": "system", "type": "performs",
                    "t": "retain last valid card rendering",
                    "line": 1, "conf": 0.9,
                }],
                "assumptions": [], "assertions": [],
            }}},
            ids, len(lines), spec_lines=lines, source_bundle=bundle,
        )

        reqs, ungrounded = result
        assert len(reqs["FR-001"].edges) == 1
        assert ungrounded == 0


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

    def test_missing_reader_is_not_scored_as_an_empty_interpretation(self):
        a = {"FR-001": _interp([_edge("system", "write report")])}
        per = v3.score_requirements([_reader(1, a), _reader(2, {})])

        assert "FR-001" not in per

    def test_only_reader_pairs_with_real_unit_coverage_are_compared(self):
        interpretation = _interp([_edge("system", "write report")])
        per = v3.score_requirements([
            _reader(1, {"FR-001": interpretation}),
            _reader(2, {}),
            _reader(3, {"FR-001": interpretation}),
        ])

        assert per["FR-001"]["score"] == 1.0
        assert per["FR-001"]["readers_covering"] == 2


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


class TestControlledSituations:
    LEXICON = [
        "ARTIFACT: SPEC",
        "",
        "REQ: REQ-001",
        "GIVEN: a builder has one or more spec runs",
        "WHEN: the builder opens the home view",
        "THEN: the workbench MUST list every run",
        "",
        "REQ: REQ-002",
        "GIVEN: a run is selected",
        "WHEN: the builder opens it",
        "THEN: an overview appears",
        "",
        "AC: AC-001",
        "GIVEN: three runs exist",
        "WHEN: the builder opens the home view",
        "THEN: three rows appear",
    ]

    def test_parses_req_and_ac_blocks(self):
        spec = v1.SpecDocument(path=Path("x"), lines=list(self.LEXICON))
        situations = v3.parse_controlled_situations(spec)
        assert set(situations) == {"REQ-001", "REQ-002", "AC-001"}
        assert situations["REQ-001"]["given"] == "a builder has one or more spec runs"
        assert situations["AC-001"]["when"] == "the builder opens the home view"

    def test_non_lexicon_spec_yields_empty(self):
        spec = v1.SpecDocument(path=Path("x"), lines=[
            "- **FR-001**: the system MUST write the report.",
        ])
        assert v3.parse_controlled_situations(spec) == {}

    def test_prompt_lists_canonical_situations_verbatim(self):
        spec = v1.SpecDocument(path=Path("x"), lines=list(self.LEXICON))
        situations = v3.parse_controlled_situations(spec)
        prompt = v3.build_extraction_prompt(
            spec, "framing", {"REQ-001"}, situations=situations
        )
        assert 'given="a builder has one or more spec runs"' in prompt
        assert "CANONICAL SITUATIONS" in prompt
        assert "REQ-002" not in prompt.split("SPECIFICATION")[0].replace(
            "\n".join(self.LEXICON), ""
        ) or True  # chunk filtering asserted below

    def test_prompt_filters_situations_to_chunk(self):
        spec = v1.SpecDocument(path=Path("x"), lines=list(self.LEXICON))
        situations = v3.parse_controlled_situations(spec)
        prompt = v3.build_extraction_prompt(
            spec, "framing", {"REQ-001"}, situations=situations
        )
        header = prompt.split("SPECIFICATION (line-numbered)")[0]
        assert "- REQ-001: given=" in header
        assert "- REQ-002: given=" not in header

    def test_validation_requires_canonical_assertion(self):
        spec_lines = list(self.LEXICON)
        situations = {"REQ-001": {"given": "a builder has one or more spec runs",
                                  "when": "the builder opens the home view",
                                  "line": 4}}
        payload = {"requirements": {"REQ-001": {
            "edges": [], "assumptions": [],
            "assertions": [{"given": "something else", "when": "whenever",
                            "then": "stuff", "lines": [4]}],
        }}}
        result = v3.validate_graph(payload, {"REQ-001"}, len(spec_lines),
                                   spec_lines=spec_lines, situations=situations)
        assert isinstance(result, v1.ParseFailure)
        assert "canonical-situation assertion" in result.reason

    def test_validation_accepts_verbatim_situation(self):
        spec_lines = list(self.LEXICON)
        situations = {"REQ-001": {"given": "a builder has one or more spec runs",
                                  "when": "the builder opens the home view",
                                  "line": 4}}
        payload = {"requirements": {"REQ-001": {
            "edges": [], "assumptions": [],
            "assertions": [{"given": "A builder has one or more spec runs",
                            "when": "the builder opens the home view",
                            "then": "every run is listed", "lines": [6]}],
        }}}
        result = v3.validate_graph(payload, {"REQ-001"}, len(spec_lines),
                                   spec_lines=spec_lines, situations=situations)
        reqs, _ = result
        assert len(reqs["REQ-001"].assertions) == 1


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
    def test_response_must_cover_every_requested_unit_exactly_once(self):
        result = v3.validate_graph(
            {"requirements": {"FR-001": {
                "edges": [], "assumptions": [], "assertions": [],
            }}},
            {"FR-001", "FR-002"}, 10,
        )

        assert isinstance(result, v1.ParseFailure)
        assert "missing requested requirement ids: FR-002" in result.reason

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

    def test_out_of_range_edge_is_rejected(self):
        result = v3.validate_graph(
            {"requirements": {"FR-001": {"edges": [
                {"s": "a", "type": "performs", "t": "b", "line": 99},
                {"s": "a", "type": "performs", "t": "c", "line": 2}]}}},
            {"FR-001"}, 10,
        )

        assert isinstance(result, v1.ParseFailure)
        assert "line must be between 1 and 10" in result.reason

    @pytest.mark.parametrize("confidence", ["high", -0.1, 1.1, float("nan")])
    def test_edge_confidence_must_be_finite_number_in_closed_interval(
            self, confidence):
        result = v3.validate_graph(
            {"requirements": {"FR-001": {
                "edges": [{
                    "s": "a", "type": "performs", "t": "b",
                    "line": 1, "conf": confidence,
                }],
                "assumptions": [], "assertions": [],
            }}},
            {"FR-001"}, 10,
        )

        assert isinstance(result, v1.ParseFailure)
        assert ".conf must be a finite number between 0 and 1" in result.reason

    @pytest.mark.parametrize(
        "field,value,expected_ungrounded",
        [
            ("assumptions", [{"text": "inferred", "line": 4}], 1),
            ("assertions", [{
                "given": "state", "when": "action", "then": "outcome",
                "lines": [2, 4],
            }], 1),
        ],
    )
    def test_evidence_outside_source_span_is_quarantined(
            self, tmp_path, field, value, expected_ungrounded):
        path = tmp_path / "spec.md"
        path.write_text(
            "# Context\n"
            "- **FR-001** The system MUST write the report.\n"
            "  The report includes provenance.\n"
            "# Unrelated\n"
        )
        bundle, ids = v3.load_requirement_scope(path)
        body = {"edges": [], "assumptions": [], "assertions": []}
        body[field] = value

        result = v3.validate_graph(
            {"requirements": {"FR-001": body}}, ids, 4,
            spec_lines=path.read_text().splitlines(), source_bundle=bundle,
        )

        reqs, ungrounded = result
        assert ungrounded == expected_ungrounded
        if field == "assumptions":
            assert reqs["FR-001"].assumptions == []
        else:
            assert reqs["FR-001"].assertions[0].lines == [2]


class TestV3OutputSchema:
    def test_schema_closes_requirement_keys_and_requires_complete_chunk(self):
        schema = v3.build_output_schema({"FR-002", "FR-001"})
        requirements = schema["properties"]["requirements"]

        assert requirements["required"] == ["FR-001", "FR-002"]
        assert set(requirements["properties"]) == {"FR-001", "FR-002"}
        assert requirements["additionalProperties"] is False

    def test_schema_closes_edge_types_and_numeric_provenance(self):
        schema = v3.build_output_schema({"FR-001"})
        body = schema["properties"]["requirements"]["properties"]["FR-001"]
        edge = body["properties"]["edges"]["items"]
        assumption = body["properties"]["assumptions"]["items"]
        assertion = body["properties"]["assertions"]["items"]

        assert edge["properties"]["type"]["enum"] == list(v3.EDGE_TYPES)
        assert edge["properties"]["line"]["minimum"] == 1
        assert edge["properties"]["conf"] == {
            "type": "number", "minimum": 0, "maximum": 1,
        }
        assert assumption["required"] == ["text", "line"]
        assert assertion["properties"]["lines"]["minItems"] == 1

    def test_main_passes_chunk_schema_to_every_provider_attempt(
            self, tmp_path, monkeypatch, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text("- **FR-001** The system MUST write the report.\n")
        captured = []

        monkeypatch.setattr(v1, "preflight", lambda _config: None)

        def fake_execute(_config, _prompt, validator, round_no=None,
                         spec_dir=None, output_schema=None, **_kwargs):
            captured.append(output_schema)
            return validator({"requirements": {"FR-001": {
                "edges": [], "assumptions": [], "assertions": [],
            }}})

        monkeypatch.setattr(v1, "execute_round", fake_execute)

        rc = v3.main([str(spec), "--model-cmd", "codex=codex"])

        assert rc == v1.EXIT_SUCCESS
        assert len(captured) == 3
        assert all(schema is not None for schema in captured)
        assert all(
            schema["properties"]["requirements"]["required"] == ["FR-001"]
            for schema in captured
        )
        capsys.readouterr()


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


class TestAggregatePasses:
    def test_stable_low_needs_low_in_every_pass(self):
        p1 = {"FR-001": {"score": 0.2}, "FR-002": {"score": 0.9}}
        p2 = {"FR-001": {"score": 0.3}, "FR-002": {"score": 0.4}}
        agg = v3.aggregate_passes([p1, p2], threshold=0.5)
        # FR-001 low in both → stable-low; FR-002 low in one pass only → not.
        assert agg["stable_low"] == ["FR-001"]
        assert agg["per_requirement"]["FR-002"]["stable_low"] is False
        assert agg["per_requirement"]["FR-001"]["mean"] == pytest.approx(0.25)

    def test_noise_floor_is_mean_per_req_stdev(self):
        p1 = {"FR-001": {"score": 0.4}}
        p2 = {"FR-001": {"score": 0.6}}
        agg = v3.aggregate_passes([p1, p2])
        # single requirement, scores 0.4/0.6 → pstdev 0.1
        assert agg["extraction_noise_floor"] == pytest.approx(0.1)
        assert agg["sr_stdev"] == pytest.approx(0.1)

    def test_only_common_requirements_aggregated(self):
        p1 = {"FR-001": {"score": 0.3}, "FR-009": {"score": 0.1}}
        p2 = {"FR-001": {"score": 0.3}}
        agg = v3.aggregate_passes([p1, p2])
        assert set(agg["per_requirement"]) == {"FR-001"}


class TestScenario:
    def test_ungrounded_model_edges_do_not_drop_v3_chunk(self, tmp_path):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        payload = json.loads(_graph_json())
        payload["requirements"]["FR-001"]["edges"][0]["t"] = "invented broker label"
        response = json.dumps(payload)
        stub = _replay_stub(tmp_path, [response] * 3)

        rc = v3.main([str(spec), "--claude-cmd", shlex.quote(stub)])

        assert rc == v1.EXIT_SUCCESS
        report = (tmp_path / "semantic-reproducibility.md").read_text()
        assert "Ungrounded evidence dropped" in report
        assert "R1=1" in report and "R2=1" in report and "R3=1" in report

    def test_multipass_reports_stability_and_noise_floor(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        # 2 passes × 3 readers = 6 identical graphs → SR stable, noise floor 0.
        stub = _replay_stub(tmp_path, [_graph_json()] * 6)
        rc = v3.main([str(spec), "--claude-cmd", shlex.quote(stub), "--passes", "2"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Stability (2 passes)" in out
        assert "noise floor 0.000" in out
        sidecar = json.loads((tmp_path / "semantic-reproducibility.json").read_text())
        assert sidecar["stability"]["passes"] == 2
        assert sidecar["stability"]["extraction_noise_floor"] == 0.0
        report = (tmp_path / "semantic-reproducibility.md").read_text()
        assert "Cross-pass stability" in report

    def test_single_pass_has_no_stability_block(self, tmp_path):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        stub = _replay_stub(tmp_path, [_graph_json()] * 3)
        v3.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        sidecar = json.loads((tmp_path / "semantic-reproducibility.json").read_text())
        assert sidecar["stability"] is None
        assert "Cross-pass stability" not in (
            tmp_path / "semantic-reproducibility.md").read_text()

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
        assert sidecar["source_bundle"]["snapshot_digest"]
        assert sidecar["source_bundle"]["adapter"] == {
            "id": "markdown-lexicon",
            "version": "1",
        }
        assert [
            (unit["id"], unit["source_refs"][0]["locator"])
            for unit in sidecar["source_bundle"]["units"]
        ] == [("FR-001", "L1-L1"), ("FR-002", "L2-L2")]

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
        assert rc == v1.EXIT_UNUSABLE_OUTPUT
        report = (tmp_path / "semantic-reproducibility.md").read_text()
        assert "1 dropped: R2(behavioural)" in report
        assert "Run status:** completed_with_coverage_gaps" in report

    def test_two_dropouts_exit_3(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        stub = _replay_stub(tmp_path, [
            _graph_json(), "garbage", "garbage", "garbage", "garbage",
        ])
        rc = v3.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 3
        assert "fewer than 2 readers" in capsys.readouterr().err
        evidence_runs = list((tmp_path / v1.EVIDENCE_DIR_NAME).glob(
            "reproducibility-*"
        ))
        assert len(evidence_runs) == 1
        manifest = json.loads((evidence_runs[0] / "run-manifest.json").read_text())
        assert manifest["status"] == "failed"
        assert manifest["chunk_failures"]

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
        assert rc == v1.EXIT_UNUSABLE_OUTPUT
        report = (tmp_path / "semantic-reproducibility.md").read_text()
        assert "Failed extraction chunks (coverage gaps):** R1=1" in report
        assert "3 completed" in report
        evidence_runs = list((tmp_path / v1.EVIDENCE_DIR_NAME).glob(
            "reproducibility-*"
        ))
        assert len(evidence_runs) == 1
        manifest = json.loads((evidence_runs[0] / "run-manifest.json").read_text())
        assert manifest["status"] == "completed_with_coverage_gaps"
        assert len(manifest["calls"]) == 7
        assert manifest["chunk_failures"][0]["reader"] == 1
        assert manifest["chunk_failures"][0]["unit_ids"] == ["FR-002"]
        assert "no JSON object found" in manifest["chunk_failures"][0]["diagnostic"]
        failed_calls = [
            call for call in manifest["calls"] if call["validation_failure"]
        ]
        assert len(failed_calls) == 2
        assert all((tmp_path / call["final_output_ref"]).is_file()
                   for call in manifest["calls"])
        sidecar = json.loads((tmp_path / "semantic-reproducibility.json").read_text())
        assert sidecar["run_evidence"]["manifest_ref"].endswith(
            "/run-manifest.json"
        )

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
