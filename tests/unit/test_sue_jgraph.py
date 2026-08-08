"""Unit tests for scripts/sue_jgraph.py (arm D — one-shot J-graph control)."""
from __future__ import annotations

import importlib.util
import json
import shlex
import stat
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


jg = _load("sue_jgraph")
v1 = jg.v1


def _claim(cid="C1", inference="stated", lines=(1,), conflicts=()):
    return {"id": cid, "claim": f"claim {cid}", "evidence_lines": list(lines),
            "assumptions": [], "inference": inference,
            "conflicts_with": list(conflicts)}


class TestValidate:
    def test_valid_graph_accepted(self):
        claims = jg.validate_graph(
            {"claims": [_claim("C1"), _claim("C2", conflicts=("C1",))]}, 10)
        assert [c.id for c in claims] == ["C1", "C2"]

    def test_stated_requires_evidence(self):
        result = jg.validate_graph({"claims": [_claim(lines=())]}, 10)
        assert isinstance(result, v1.ParseFailure)
        assert "stated claims require" in result.reason

    def test_derived_may_lack_evidence(self):
        claims = jg.validate_graph(
            {"claims": [_claim(inference="derived", lines=())]}, 10)
        assert claims[0].inference == "derived"

    def test_unknown_conflict_ref_rejected(self):
        result = jg.validate_graph(
            {"claims": [_claim(conflicts=("C9",))]}, 10)
        assert isinstance(result, v1.ParseFailure)
        assert "unknown id" in result.reason

    def test_duplicate_id_rejected(self):
        result = jg.validate_graph(
            {"claims": [_claim("C1"), _claim("C1")]}, 10)
        assert isinstance(result, v1.ParseFailure)


def _reader(*claim_dicts):
    return jg.validate_graph({"claims": list(claim_dicts)}, 100)


class TestConvergence:
    def test_conflict_on_same_lines_converges_across_readers(self):
        # Two readers both flag a conflict between line-1 and line-2 claims.
        r1 = _reader(_claim("C1", lines=(1,), conflicts=("C2",)),
                     _claim("C2", lines=(2,)))
        r2 = _reader(_claim("C1", lines=(1,), conflicts=("C2",)),
                     _claim("C2", lines=(2,)))
        clusters = jg.consensus_conflicts({1: r1, 2: r2})
        assert len(clusters) == 1
        assert clusters[0]["readers"] == {1, 2}
        conv = jg.convergence_metrics({1: r1, 2: r2}, clusters)
        assert conv["consensus_conflicts"] == 1
        assert conv["unanimous_conflicts"] == 1
        assert conv["conflict_convergence"] == 1.0

    def test_conflict_orientation_agnostic(self):
        # reader 2 lists the same pair in the opposite direction/order.
        r1 = _reader(_claim("C1", lines=(1,), conflicts=("C2",)),
                     _claim("C2", lines=(2,)))
        r2 = _reader(_claim("C1", lines=(2,), conflicts=("C2",)),
                     _claim("C2", lines=(1,)))
        clusters = jg.consensus_conflicts({1: r1, 2: r2})
        assert len(clusters) == 1 and clusters[0]["readers"] == {1, 2}

    def test_disjoint_conflicts_do_not_converge(self):
        r1 = _reader(_claim("C1", lines=(1,), conflicts=("C2",)),
                     _claim("C2", lines=(2,)))
        r2 = _reader(_claim("C1", lines=(5,), conflicts=("C2",)),
                     _claim("C2", lines=(6,)))
        clusters = jg.consensus_conflicts({1: r1, 2: r2})
        conv = jg.convergence_metrics({1: r1, 2: r2}, clusters)
        assert conv["distinct_conflicts"] == 2
        assert conv["consensus_conflicts"] == 0
        assert conv["conflict_convergence"] == 0.0

    def test_single_reader_conflict_is_not_consensus(self):
        r1 = _reader(_claim("C1", lines=(1,), conflicts=("C2",)),
                     _claim("C2", lines=(2,)))
        r2 = _reader(_claim("C1", lines=(1,)))  # no conflict
        clusters = jg.consensus_conflicts({1: r1, 2: r2})
        conv = jg.convergence_metrics({1: r1, 2: r2}, clusters)
        assert conv["consensus_conflicts"] == 0


class TestMetrics:
    def test_completeness_and_pairs_dedupe(self):
        claims = jg.validate_graph({"claims": [
            _claim("C1", conflicts=("C2",)),
            _claim("C2", conflicts=("C1",)),
            _claim("C3", inference="derived", lines=()),
        ]}, 10)
        metrics = jg.graph_metrics({1: claims})
        assert metrics[1]["claims"] == 3
        assert metrics[1]["conflict_pairs"] == [["C1", "C2"]]
        assert abs(metrics[1]["evidence_completeness"] - 2 / 3) < 1e-9


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
    def test_full_run_writes_reports(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text("FR-001: a\nAC-5: b\n")
        graph = json.dumps({"claims": [
            _claim("C1", lines=(1,)),
            _claim("C2", lines=(2,), conflicts=("C1",)),
        ]})
        stub = _replay_stub(tmp_path, [graph] * 3)
        rc = jg.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 0
        sidecar = json.loads((tmp_path / "justification-graph.json").read_text())
        assert sidecar["metrics"]["1"]["conflict_pairs"] == [["C1", "C2"]]
        report = (tmp_path / "justification-graph.md").read_text()
        assert "⚡ conflicts: C1" in report
        # All 3 readers report the same conflict → converged & unanimous.
        assert sidecar["convergence"]["consensus_conflicts"] == 1
        assert sidecar["convergence"]["unanimous_conflicts"] == 1
        assert sidecar["consensus_conflicts"][0]["support"] == 3
        assert "Consensus conflicts" in report
        out = capsys.readouterr().out
        assert "conflict pairs total: 3" in out
        assert "Convergence: 1/1" in out

    def test_all_readers_failing_exit_3(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text("FR-001: a\n")
        stub = _replay_stub(tmp_path, ["garbage"] * 6)
        rc = jg.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 3
        capsys.readouterr()
