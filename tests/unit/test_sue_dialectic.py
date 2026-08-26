"""Unit tests for scripts/sue_dialectic.py (arm C — adaptive elenchus engine).

Design: docs/superpowers/specs/2026-07-19-sue-dialectic-design-draft.md
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


dial = _load("sue_dialectic")
v1 = dial.v1


class TestQuestionTemplates:
    def test_deterministic_and_parameterized(self):
        q1 = dial.build_question("DEFINE", "busy run", "claim", "")
        q2 = dial.build_question("DEFINE", "busy run", "claim", "")
        assert q1 == q2
        assert '"busy run"' in q1

    def test_all_operators_have_templates(self):
        for op in dial.OPERATORS:
            text = dial.build_question(op, "f", "c", "fail")
            assert isinstance(text, str) and len(text) > 20


class TestPolicies:
    def test_all_lenses_total_over_verdicts(self):
        """Every reachable (operator, verdict) pair must resolve — walk each
        lens's operator set plus the shared operators."""
        for lens, spec in dial.LENSES.items():
            reachable = {spec["start"]}
            for (op, _v), nxt in {**dial._SHARED_POLICY, **spec["policy"]}.items():
                reachable.add(op)
                if nxt in dial.OPERATORS:
                    reachable.add(nxt)
            for op in reachable:
                for verdict in dial.TURN_VERDICTS:
                    step = dial.next_step(lens, op, verdict, "none", 0)
                    assert step in dial.OPERATORS or step in dial.TERMINALS

    def test_examples_are_not_a_definition(self):
        step = dial.next_step("euthyphro", "DEFINE", "SUPPORTED", "example", 0)
        assert step == "DISTINGUISH"

    def test_counterexample_found_leads_to_revision(self):
        assert dial.next_step("euthyphro", "COUNTEREXAMPLE", "SUPPORTED",
                              "none", 0) == "REVISE"

    def test_revision_budget_converts_to_aporia(self):
        assert dial.next_step("euthyphro", "COUNTEREXAMPLE", "SUPPORTED",
                              "none", dial.MAX_REVISIONS) == "APORIA_CONTRADICTED"

    def test_parmenides_tolerated_opposite_is_underdetermined(self):
        assert dial.next_step("parmenides", "TEST_OPPOSITE", "SILENT",
                              "none", 0) == "APORIA_UNDERDETERMINED"

    def test_meno_no_criterion_is_undefined(self):
        assert dial.next_step("meno", "CAUSE_OR_CRITERION", "SILENT",
                              "none", 0) == "APORIA_UNDEFINED"

    def test_cratylus_unstable_naming_is_underdetermined(self):
        assert dial.next_step("cratylus", "DISTINGUISH", "SILENT",
                              "none", 0) == "APORIA_UNDERDETERMINED"

    def test_lens_roster_is_nine(self):
        assert sorted(dial.LENSES) == [
            "cratylus", "euthyphro", "gorgias", "meno", "parmenides",
            "philebus", "republic", "sophist", "theaetetus"]

    def test_lens_state_machines_are_closed_under_refinement(self):
        """DEFINE/SUPPORTED/example rewrites to DISTINGUISH in every lens, so
        any lens that can reach DEFINE must resolve DISTINGUISH for every
        verdict — a missing entry would KeyError mid-dialogue."""
        for lens, spec in dial.LENSES.items():
            merged = {**dial._SHARED_POLICY, **spec["policy"]}
            reachable = {spec["start"]} | {
                n for n in merged.values() if n in dial.OPERATORS}
            if "DEFINE" in reachable:
                for verdict in dial.TURN_VERDICTS:
                    step = dial.next_step(lens, "DISTINGUISH", verdict, "none", 0)
                    assert step in dial.OPERATORS or step in dial.TERMINALS

    # ── The five 2026-07-20 lenses: one signature transition each ──

    def test_theaetetus_unjustified_claim_is_undefined(self):
        # Knowledge without an account: a claim whose justification the text
        # cannot supply is APORIA_UNDEFINED, not merely unanswered.
        assert dial.next_step("theaetetus", "CAUSE_OR_CRITERION", "SILENT",
                              "none", 0) == "APORIA_UNDEFINED"

    def test_theaetetus_justification_is_tested_by_consequence(self):
        # Distinct from meno (criterion -> COUNTEREXAMPLE): theaetetus tests
        # whether the justification itself entails what is claimed.
        assert dial.next_step("theaetetus", "CAUSE_OR_CRITERION", "SUPPORTED",
                              "criterion", 0) == "FOLLOW_CONSEQUENCE"

    def test_sophist_division_leads_to_lookalike_distinction(self):
        # Distinct from the shared DIVIDE -> COUNTEREXAMPLE: sophist separates
        # the look-alike cases before hunting violations.
        assert dial.next_step("sophist", "DIVIDE", "SUPPORTED",
                              "case-split", 0) == "DISTINGUISH"

    def test_sophist_tolerated_excluded_case_is_underdetermined(self):
        # The M3 drill: if the text tolerates the supposedly-excluded case,
        # the boundary is missing.
        assert dial.next_step("sophist", "TEST_OPPOSITE", "SILENT",
                              "none", 0) == "APORIA_UNDERDETERMINED"

    def test_gorgias_silent_consequences_are_rhetoric_not_resolution(self):
        # Overrides the shared FOLLOW_CONSEQUENCE/SILENT -> RESOLVED: in
        # gorgias, a claim with no textual commitments is rhetoric.
        assert dial.next_step("gorgias", "FOLLOW_CONSEQUENCE", "SILENT",
                              "none", 0) == "APORIA_UNDEFINED"

    def test_republic_unseparated_actors_are_undefined(self):
        assert dial.next_step("republic", "DISTINGUISH", "SILENT",
                              "none", 0) == "APORIA_UNDEFINED"

    def test_republic_permission_criterion_hunts_counterexample(self):
        # The FR-001xAC-5 move: permission criterion stated -> seek the actor
        # case that violates it.
        assert dial.next_step("republic", "CAUSE_OR_CRITERION", "SUPPORTED",
                              "criterion", 0) == "COUNTEREXAMPLE"

    def test_philebus_no_measure_is_undefined(self):
        # The unlimited: a constraint with no stated bound.
        assert dial.next_step("philebus", "DEFINE", "SILENT",
                              "none", 0) == "APORIA_UNDEFINED"

    def test_philebus_stated_bound_is_tested_by_opposite(self):
        # Distinct from euthyphro (DEFINE -> COUNTEREXAMPLE): philebus asks
        # what would violate the measure.
        assert dial.next_step("philebus", "DEFINE", "SUPPORTED",
                              "definition", 0) == "TEST_OPPOSITE"


class TestValidateTurn:
    def test_supported_requires_evidence(self):
        result = dial.validate_turn(
            {"answer": "a", "verdict": "SUPPORTED", "answer_type": "definition",
             "evidence_lines": [], "claim": "c"}, "DEFINE", 10)
        assert isinstance(result, v1.ParseFailure)

    def test_silent_forbids_evidence(self):
        result = dial.validate_turn(
            {"answer": "a", "verdict": "SILENT", "answer_type": "none",
             "evidence_lines": [3]}, "DEFINE", 10)
        assert isinstance(result, v1.ParseFailure)

    def test_define_supported_requires_claim(self):
        result = dial.validate_turn(
            {"answer": "a", "verdict": "SUPPORTED", "answer_type": "definition",
             "evidence_lines": [3]}, "DEFINE", 10)
        assert isinstance(result, v1.ParseFailure)
        assert "must state a claim" in result.reason

    def test_valid_turn_accepted(self):
        result = dial.validate_turn(
            {"answer": "the text defines it", "verdict": "SUPPORTED",
             "answer_type": "definition", "evidence_lines": [3, 99],
             "claim": "an edit is invalid when parsing fails"}, "DEFINE", 10)
        assert result["evidence_lines"] == [3]  # out-of-range dropped
        assert result["claim"].startswith("an edit")


def _turn_json(verdict, answer_type="none", lines=(3,), claim=None, answer="a"):
    payload = {"answer": answer, "verdict": verdict, "answer_type": answer_type,
               "evidence_lines": list(lines)}
    if claim:
        payload["claim"] = claim
    return json.dumps(payload)


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


_SPEC = "\n".join([
    "- **FR-001**: anyone with at least one role may edit a row.",
    "- **AC-5**: an operator with only WHO responsibility sees no edit affordances.",
    "- **FR-002**: edits persist immediately.",
])


class TestScenario:
    def _run(self, tmp_path, responses, lens="euthyphro", max_turns=7):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        stub = _replay_stub(tmp_path, responses)
        rc = dial.main([str(spec), "--lens", lens, "--seed",
                        "who may edit a row", "--claude-cmd",
                        shlex.quote(stub), "--max-turns", str(max_turns)])
        return rc, tmp_path

    def test_contradiction_path_reaches_aporia(self, tmp_path, capsys):
        # DEFINE(SUPPORTED/definition) -> COUNTEREXAMPLE(SUPPORTED: found)
        # -> REVISE(SILENT: text cannot repair) -> APORIA_CONTRADICTED
        responses = [
            _turn_json("SUPPORTED", "definition", (1,),
                       claim="anyone with >=1 role may edit"),
            _turn_json("SUPPORTED", "example", (2,),
                       answer="AC-5: WHO-only operator sees no edit affordances"),
            _turn_json("SILENT", "none", ()),
        ]
        rc, base = self._run(tmp_path, responses)
        assert rc == 0
        trace = json.loads((base / "socratic-dialogue.json").read_text())
        assert trace["terminal_state"] == "APORIA_CONTRADICTED"
        assert [t["operator"] for t in trace["turns"]] == [
            "DEFINE", "COUNTEREXAMPLE", "REVISE"]
        out = capsys.readouterr().out
        assert "APORIA_CONTRADICTED" in out

    def test_resolved_path(self, tmp_path):
        # DEFINE(SUPPORTED/definition) -> COUNTEREXAMPLE(SILENT: none)
        # -> FOLLOW_CONSEQUENCE(SUPPORTED) -> RESOLVED
        responses = [
            _turn_json("SUPPORTED", "definition", (1,), claim="c"),
            _turn_json("SILENT", "none", ()),
            _turn_json("SUPPORTED", "consequence", (3,)),
        ]
        rc, base = self._run(tmp_path, responses)
        assert rc == 0
        trace = json.loads((base / "socratic-dialogue.json").read_text())
        assert trace["terminal_state"] == "RESOLVED"

    def test_bounded_stop(self, tmp_path):
        # DIVIDE(SUPPORTED) -> COUNTEREXAMPLE(PARTIAL) loop until max-turns.
        responses = [
            _turn_json("SUPPORTED", "definition", (1,), claim="c"),
        ] + [
            _turn_json("PARTIAL", "case-split", (2,)),
            _turn_json("SUPPORTED", "case-split", (2,)),
        ] * 4
        rc, base = self._run(tmp_path, responses, max_turns=4)
        assert rc == 0
        trace = json.loads((base / "socratic-dialogue.json").read_text())
        assert trace["terminal_state"] == "BOUNDED_STOP"
        assert len(trace["turns"]) == 4

    def test_retention_flag_on_evidence_abandoning_revision(self, tmp_path):
        # DEFINE cites line 1; COUNTEREXAMPLE cites line 2; REVISE cites ONLY
        # line 3 (abandons 1 and 2) -> flagged, dialogue continues.
        responses = [
            _turn_json("SUPPORTED", "definition", (1,), claim="c1"),
            _turn_json("SUPPORTED", "example", (2,)),
            _turn_json("SUPPORTED", "revision", (3,), claim="c2"),
            _turn_json("SILENT", "none", ()),          # COUNTEREXAMPLE: none
            _turn_json("SUPPORTED", "consequence", (3,)),
        ]
        rc, base = self._run(tmp_path, responses)
        assert rc == 0
        trace = json.loads((base / "socratic-dialogue.json").read_text())
        revise_turns = [t for t in trace["turns"] if t["operator"] == "REVISE"]
        assert revise_turns[0]["retention_violation"] is True
        report = (base / "socratic-dialogue.md").read_text()
        assert "RETENTION" in report

    def test_gorgias_thin_text_reaches_undefined_aporia(self, tmp_path):
        # FOLLOW_CONSEQUENCE(SILENT) -> APORIA_UNDEFINED in one turn:
        # persuasive text with no commitments is rhetoric, never RESOLVED.
        responses = [_turn_json("SILENT", "none", ())]
        rc, base = self._run(tmp_path, responses, lens="gorgias")
        assert rc == 0
        trace = json.loads((base / "socratic-dialogue.json").read_text())
        assert trace["terminal_state"] == "APORIA_UNDEFINED"
        assert [t["operator"] for t in trace["turns"]] == ["FOLLOW_CONSEQUENCE"]

    def test_sophist_missing_boundary_path(self, tmp_path):
        # DIVIDE(SUPPORTED) -> DISTINGUISH(SUPPORTED) -> TEST_OPPOSITE(SILENT)
        # -> APORIA_UNDERDETERMINED: the text tolerates the excluded case.
        responses = [
            _turn_json("SUPPORTED", "case-split", (1,)),
            _turn_json("SUPPORTED", "distinction", (2,)),
            _turn_json("SILENT", "none", ()),
        ]
        rc, base = self._run(tmp_path, responses, lens="sophist")
        assert rc == 0
        trace = json.loads((base / "socratic-dialogue.json").read_text())
        assert trace["terminal_state"] == "APORIA_UNDERDETERMINED"
        assert [t["operator"] for t in trace["turns"]] == [
            "DIVIDE", "DISTINGUISH", "TEST_OPPOSITE"]

    def test_turn_failure_after_retry_exits_3(self, tmp_path, capsys):
        rc, _ = self._run(tmp_path, ["garbage", "garbage"])
        assert rc == 3
        capsys.readouterr()

    def test_missing_seed_is_bad_input(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        rc = dial.main([str(spec)])
        assert rc == 1
        capsys.readouterr()

    def test_report_collision_guard(self, tmp_path, capsys):
        spec = tmp_path / "socratic-dialogue.md"
        spec.write_text("previous\n")
        rc = dial.main([str(spec), "--seed", "x"])
        assert rc == 1
        assert spec.read_text() == "previous\n"
        capsys.readouterr()
