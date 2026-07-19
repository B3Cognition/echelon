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
        out = capsys.readouterr().out
        assert "conflict pairs total: 3" in out

    def test_all_readers_failing_exit_3(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text("FR-001: a\n")
        stub = _replay_stub(tmp_path, ["garbage"] * 6)
        rc = jg.main([str(spec), "--claude-cmd", shlex.quote(stub)])
        assert rc == 3
        capsys.readouterr()
