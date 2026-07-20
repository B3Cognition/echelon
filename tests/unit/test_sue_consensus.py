"""Unit tests for scripts/sue_consensus.py (SUE v2 — consensus + elenchus).

Design: docs/superpowers/specs/2026-07-19-sue-v2-consensus-design.md
Offline throughout: model calls replayed via counter-based stub executables.
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


v2 = _load("sue_consensus")
v1 = v2.v1


def _q(qid="Q1", target="REQ-001", category="ambiguity", text="what is X?"):
    return v1.SocraticQuestion(
        id=qid, question=text, target=target, lines=[5], category=category
    )


def _finding(reader_lines, target="REQ-001", category="ambiguity",
             verdict="UNANSWERABLE", text="what is X?"):
    return v1.Finding(
        rank=0,
        question=_q(target=target, category=category, text=text),
        answer=v1.Answer(
            id="Q1", verdict=verdict, answer="the text is silent",
            evidence_lines=list(reader_lines),
        ),
    )


def _reader(no, findings, framing="structural"):
    return v2.ReaderResult(
        reader_no=no, framing=framing, findings=findings, answered_count=0
    )


class TestClustering:
    def test_same_anchor_overlapping_lines_cluster(self):
        readers = [
            _reader(1, [_finding([4, 5])]),
            _reader(2, [_finding([5, 6])]),
        ]
        clusters = v2.cluster_findings(readers)
        assert len(clusters) == 1
        assert clusters[0].support == 2

    def test_different_target_never_clusters(self):
        readers = [
            _reader(1, [_finding([5], target="REQ-001")]),
            _reader(2, [_finding([5], target="REQ-002")]),
        ]
        assert len(v2.cluster_findings(readers)) == 2

    def test_different_category_never_clusters(self):
        readers = [
            _reader(1, [_finding([5], category="ambiguity")]),
            _reader(2, [_finding([5], category="contradiction")]),
        ]
        assert len(v2.cluster_findings(readers)) == 2

    def test_disjoint_lines_never_cluster(self):
        readers = [
            _reader(1, [_finding([5])]),
            _reader(2, [_finding([9])]),
        ]
        assert len(v2.cluster_findings(readers)) == 2

    def test_both_empty_evidence_clusters(self):
        readers = [
            _reader(1, [_finding([])]),
            _reader(2, [_finding([])]),
        ]
        assert len(v2.cluster_findings(readers)) == 1

    def test_support_counts_distinct_readers_not_findings(self):
        readers = [
            _reader(1, [_finding([5]), _finding([5], text="variant same gap")]),
            _reader(2, []),
        ]
        clusters = v2.cluster_findings(readers)
        assert len(clusters) == 1
        assert clusters[0].support == 1

    def test_representative_is_lowest_reader(self):
        readers = [
            _reader(2, [_finding([5], text="from R2")]),
            _reader(1, [_finding([5], text="from R1")]),
        ]
        cluster = v2.cluster_findings(readers)[0]
        assert cluster.representative.question.question == "from R1"

    def test_worst_verdict_prefers_contradicted(self):
        readers = [
            _reader(1, [_finding([5], verdict="UNANSWERABLE")]),
            _reader(2, [_finding([5], verdict="CONTRADICTED")]),
        ]
        assert v2.cluster_findings(readers)[0].worst_verdict == "CONTRADICTED"


class TestSplitStable:
    def test_threshold_and_ordering(self):
        readers = [
            _reader(1, [
                _finding([5], target="REQ-001"),
                _finding([9], target="REQ-002", verdict="CONTRADICTED"),
                _finding([12], target="REQ-003"),
            ]),
            _reader(2, [
                _finding([5], target="REQ-001"),
                _finding([9], target="REQ-002", verdict="CONTRADICTED"),
            ]),
        ]
        stable, noise = v2.split_stable(v2.cluster_findings(readers), 2)
        assert [c.target for c in stable] == ["REQ-002", "REQ-001"]
        assert [c.target for c in noise] == ["REQ-003"]


class TestChainValidation:
    def _stable(self):
        readers = [
            _reader(1, [_finding([5, 6])]),
            _reader(2, [_finding([5])]),
        ]
        stable, _ = v2.split_stable(v2.cluster_findings(readers), 2)
        return stable

    def test_valid_followup_accepted(self):
        stable = self._stable()
        result = v2.validate_followups(
            {"followups": [{"id": "F1", "parent": "C1",
                            "question": "which decision closes X?",
                            "premise_lines": [5]}]},
            stable,
        )
        assert isinstance(result, list) and result[0].parent == "C1"

    def test_unknown_parent_rejected(self):
        result = v2.validate_followups(
            {"followups": [{"id": "F1", "parent": "C9", "question": "q?",
                            "premise_lines": [5]}]},
            self._stable(),
        )
        assert isinstance(result, v1.ParseFailure)
        assert "names no stable cluster" in result.reason

    def test_broken_chain_rejected(self):
        result = v2.validate_followups(
            {"followups": [{"id": "F1", "parent": "C1", "question": "q?",
                            "premise_lines": [99]}]},
            self._stable(),
        )
        assert isinstance(result, v1.ParseFailure)
        assert "breaks the chain" in result.reason

    def test_missing_cluster_coverage_rejected(self):
        readers = [
            _reader(1, [_finding([5]), _finding([9], target="REQ-002")]),
            _reader(2, [_finding([5]), _finding([9], target="REQ-002")]),
        ]
        stable, _ = v2.split_stable(v2.cluster_findings(readers), 2)
        result = v2.validate_followups(
            {"followups": [{"id": "F1", "parent": "C1", "question": "q?",
                            "premise_lines": [5]}]},
            stable,
        )
        assert isinstance(result, v1.ParseFailure)
        assert "no follow-up produced" in result.reason

    def test_parent_without_evidence_exempt_from_premise(self):
        readers = [
            _reader(1, [_finding([])]),
            _reader(2, [_finding([])]),
        ]
        stable, _ = v2.split_stable(v2.cluster_findings(readers), 2)
        result = v2.validate_followups(
            {"followups": [{"id": "F1", "parent": "C1", "question": "q?",
                            "premise_lines": []}]},
            stable,
        )
        assert isinstance(result, list)


class TestRetentionFlag:
    def test_flags_answered_with_abandoned_evidence(self):
        parent = _finding([5, 6])
        child = v1.Answer(id="Q1", verdict="ANSWERED", answer="a",
                          evidence_lines=[20])
        assert v2.retention_flag(parent, child) is True

    def test_no_flag_when_evidence_retained(self):
        parent = _finding([5, 6])
        child = v1.Answer(id="Q1", verdict="ANSWERED", answer="a",
                          evidence_lines=[6, 20])
        assert v2.retention_flag(parent, child) is False

    def test_no_flag_for_unanswerable_child(self):
        parent = _finding([5])
        child = v1.Answer(id="Q1", verdict="UNANSWERABLE", answer="a",
                          evidence_lines=[])
        assert v2.retention_flag(parent, child) is False


# ── Scenario tests with a counter-based replay stub ─────────────────────────


_SPEC = "\n".join(f"REQ-{i:03d}: the system shall do thing {i}." for i in range(1, 8))


def _round1(qid_target_pairs):
    return json.dumps({
        "questions": [
            {"id": qid, "question": f"is {target} complete?", "target": target,
             "lines": [int(target[-1])], "category": "ambiguity"}
            for qid, target in qid_target_pairs
        ]
    })


def _round2(verdict_by_id, lines_by_id=None):
    lines_by_id = lines_by_id or {}
    return json.dumps({
        "answers": [
            {"id": qid, "verdict": verdict,
             "answer": f"analysis of {qid}",
             "evidence_lines": lines_by_id.get(qid, [1])}
            for qid, verdict in verdict_by_id.items()
        ]
    })


def _replay_stub(tmp_path: Path, responses: list[str]) -> str:
    """Executable emitting responses[n] on its n-th invocation."""
    payload_dir = tmp_path / "replay"
    payload_dir.mkdir()
    for index, response in enumerate(responses):
        (payload_dir / f"{index}.json").write_text(response)
    counter = payload_dir / "count"
    counter.write_text("0")
    stub = tmp_path / "stub.sh"
    stub.write_text(
        "#!/bin/sh\ncat > /dev/null\n"
        f'N=$(cat "{counter}")\n'
        f'echo $((N + 1)) > "{counter}"\n'
        f'cat "{payload_dir}/$N.json"\n'
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return str(stub)


def _write_spec(tmp_path: Path) -> Path:
    spec = tmp_path / "spec.md"
    spec.write_text(_SPEC + "\n")
    return spec


class TestScenario:
    def test_full_run_stable_finding_with_chain(self, tmp_path, capsys):
        # 3 readers ask about REQ-001 line 1; readers 1+2 get UNANSWERABLE
        # (stable), reader 3 ANSWERED. Elenchus chains on the survivor.
        responses = [
            _round1([("Q1", "REQ-001")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
            _round1([("Q1", "REQ-001")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
            _round1([("Q1", "REQ-001")]),
            _round2({"Q1": "ANSWERED"}, {"Q1": [1]}),
            json.dumps({"followups": [{"id": "F1", "parent": "C1",
                                       "question": "which decision closes it?",
                                       "premise_lines": [1]}]}),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
        ]
        stub = _replay_stub(tmp_path, responses)
        spec = _write_spec(tmp_path)
        rc = v2.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        report = (tmp_path / "socratic-consensus.md").read_text()
        assert "support 2" in report
        assert "Elenchus [UNANSWERABLE]" in report
        assert "which decision closes it?" in report
        out = capsys.readouterr().out
        assert "Stable findings" in out

    def test_one_reader_two_findings_same_cluster_renders(self, tmp_path):
        """Live regression (spec 018/025): a reader contributing 2+ findings
        to one cluster must not crash the variants sort (Finding < Finding)."""
        responses = [
            _round1([("Q1", "REQ-001"), ("Q2", "REQ-001")]),
            _round2({"Q1": "UNANSWERABLE", "Q2": "UNANSWERABLE"},
                    {"Q1": [1], "Q2": [1]}),
            _round1([("Q1", "REQ-001")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
            _round1([("Q1", "REQ-001")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
            json.dumps({"followups": [{"id": "F1", "parent": "C1",
                                       "question": "q?", "premise_lines": [1]}]}),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
        ]
        stub = _replay_stub(tmp_path, responses)
        spec = _write_spec(tmp_path)
        rc = v2.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        report = (tmp_path / "socratic-consensus.md").read_text()
        assert "support 3" in report

    def test_no_stable_findings_skips_elenchus(self, tmp_path):
        # Readers disagree on targets: three singleton clusters, no elenchus
        # calls consumed (stub would fail if a 7th call happened).
        responses = [
            _round1([("Q1", "REQ-001")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
            _round1([("Q1", "REQ-002")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [2]}),
            _round1([("Q1", "REQ-003")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [3]}),
        ]
        stub = _replay_stub(tmp_path, responses)
        spec = _write_spec(tmp_path)
        rc = v2.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        report = (tmp_path / "socratic-consensus.md").read_text()
        assert "skipped — no stable findings" in report
        assert "Sampling appendix" in report

    def test_one_reader_dropped_run_degrades(self, tmp_path):
        # Reader 2's two attempts both emit garbage -> RoundExit -> dropped;
        # readers 1+3 proceed, cluster is stable at support 2.
        responses = [
            _round1([("Q1", "REQ-001")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
            "garbage", "garbage",
            _round1([("Q1", "REQ-001")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
            json.dumps({"followups": [{"id": "F1", "parent": "C1",
                                       "question": "q?", "premise_lines": [1]}]}),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
        ]
        stub = _replay_stub(tmp_path, responses)
        spec = _write_spec(tmp_path)
        rc = v2.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        report = (tmp_path / "socratic-consensus.md").read_text()
        assert "1 dropped: R2(behavioural)" in report

    def test_two_readers_dropped_exits_3(self, tmp_path, capsys):
        responses = [
            _round1([("Q1", "REQ-001")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
            "garbage", "garbage",
            "garbage", "garbage",
        ]
        stub = _replay_stub(tmp_path, responses)
        spec = _write_spec(tmp_path)
        rc = v2.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 3
        err = capsys.readouterr().err
        assert "fewer than 2 readers" in err
        assert err.count("\n") == 1

    def test_no_elenchus_flag(self, tmp_path):
        responses = [
            _round1([("Q1", "REQ-001")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
            _round1([("Q1", "REQ-001")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
            _round1([("Q1", "REQ-001")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
        ]
        stub = _replay_stub(tmp_path, responses)
        spec = _write_spec(tmp_path)
        rc = v2.main([str(spec), "--claude-cmd", shlex.quote(stub),
                      "--no-elenchus"])
        assert rc == 0
        report = (tmp_path / "socratic-consensus.md").read_text()
        assert "disabled (--no-elenchus)" in report

    def test_retention_flag_rendered(self, tmp_path):
        responses = [
            _round1([("Q1", "REQ-001")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
            _round1([("Q1", "REQ-001")]),
            _round2({"Q1": "UNANSWERABLE"}, {"Q1": [1]}),
            _round1([("Q1", "REQ-002")]),
            _round2({"Q1": "ANSWERED"}, {"Q1": [2]}),
            json.dumps({"followups": [{"id": "F1", "parent": "C1",
                                       "question": "q?", "premise_lines": [1]}]}),
            # Chain answer claims ANSWERED citing entirely different evidence.
            _round2({"Q1": "ANSWERED"}, {"Q1": [7]}),
        ]
        stub = _replay_stub(tmp_path, responses)
        spec = _write_spec(tmp_path)
        rc = v2.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        report = (tmp_path / "socratic-consensus.md").read_text()
        assert "RETENTION-CHECK" in report

    def test_empty_spec_exit_1(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text("   \n\n")
        stub = _replay_stub(tmp_path, [])
        rc = v2.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "empty or whitespace-only" in err

    def test_report_path_collision_rejected(self, tmp_path, capsys):
        spec = tmp_path / "socratic-consensus.md"
        spec.write_text("previous report\n")
        stub = _replay_stub(tmp_path, [])
        rc = v2.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 1
        assert spec.read_text() == "previous report\n"
        capsys.readouterr()
