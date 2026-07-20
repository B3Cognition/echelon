"""Unit tests for scripts/sue_auto.py (autonomic pipeline orchestrator).

Design: docs/superpowers/specs/2026-07-20-sue-auto-orchestrator-design.md
Offline throughout: pure units + monkeypatched tool mains + one true replay-stub
end-to-end for the lite profile.
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


auto = _load("sue_auto")


class TestLensSelection:
    def test_contradicted_goes_to_parmenides(self):
        assert auto.choose_lens("CONTRADICTED", "anything") == "parmenides"

    def test_definition_question_goes_to_euthyphro(self):
        assert auto.choose_lens(
            "UNANSWERABLE", "What does a busy run mean here?") == "euthyphro"

    def test_verification_question_goes_to_meno(self):
        assert auto.choose_lens(
            "UNANSWERABLE", "How would one verify the retry happened?") == "meno"

    def test_actor_question_goes_to_republic(self):
        assert auto.choose_lens(
            "UNANSWERABLE", "Who may edit a locked row?") == "republic"

    def test_bound_question_goes_to_philebus(self):
        assert auto.choose_lens(
            "UNANSWERABLE", "How long may the run take at most?") == "philebus"

    def test_default_goes_to_theaetetus(self):
        assert auto.choose_lens(
            "UNANSWERABLE", "Why is the report written twice?") == "theaetetus"

    def test_unit_family_lenses(self):
        assert auto.lens_for_unit("NFR-002") == "philebus"
        assert auto.lens_for_unit("ERR-004") == "sophist"
        assert auto.lens_for_unit("AC-017") == "theaetetus"
        assert auto.lens_for_unit("FR-009") == "euthyphro"
        assert auto.lens_for_unit("REQ-003") == "euthyphro"


class TestProfiles:
    def test_profile_names(self):
        assert sorted(auto.PROFILES) == ["deep", "forensic", "lite"]

    def test_lite_is_v1_only_no_drills(self):
        profile = auto.PROFILES["lite"]
        assert profile.tiers == ("v1",)
        assert profile.drill_cap == 0

    def test_deep_orders_measure_after_consensus(self):
        assert auto.PROFILES["deep"].tiers == ("v2", "v3", "drills")

    def test_forensic_adds_jgraph(self):
        assert auto.PROFILES["forensic"].tiers == ("v2", "v3", "jgraph", "drills")

    def test_plan_calls_lite_exact(self):
        assert auto.plan_calls("lite", unit_count=50) == 2

    def test_plan_calls_scale_with_units_and_depth(self):
        deep_small = auto.plan_calls("deep", unit_count=10)
        deep_large = auto.plan_calls("deep", unit_count=90)
        assert deep_small < deep_large
        assert auto.plan_calls("lite", 90) < deep_large < auto.plan_calls(
            "forensic", 90)


_V2_REPORT = """# Socratic Consensus Report

- **Specification:** x/spec.md
- **Stable findings:** 2 · sampling noise: 3

## Stable findings

### 1. [CONTRADICTED] (support 3) Which timeout applies to round 2?

- **Target:** FR-011
- **Category:** contradiction
- **Evidence:**
  > line 4: ...

### 2. [UNANSWERABLE] (support 2) Who may rerun a completed challenge?

- **Target:** AC-003
- **Category:** completeness

## Sampling appendix (noise)

### 1. [UNANSWERABLE] (support 1) Noise question never parsed?

- **Target:** FR-099
"""


class TestParseStableFindings:
    def test_parses_only_stable_section(self):
        findings = auto.parse_stable_findings(_V2_REPORT)
        assert [f["verdict"] for f in findings] == ["CONTRADICTED", "UNANSWERABLE"]
        assert findings[0]["support"] == 3
        assert findings[0]["question"] == "Which timeout applies to round 2?"
        assert findings[0]["target"] == "FR-011"
        assert findings[1]["target"] == "AC-003"

    def test_empty_report_yields_no_findings(self):
        assert auto.parse_stable_findings("# Report\n\nNone.\n") == []


class TestSelectDrills:
    def test_findings_first_then_stable_low_fill(self):
        findings = [
            {"verdict": "CONTRADICTED", "support": 3,
             "question": "Which timeout applies?", "target": "FR-011"},
        ]
        drills = auto.select_drills(findings, ["NFR-002", "AC-017"], cap=3)
        assert [d["target"] for d in drills] == ["FR-011", "NFR-002", "AC-017"]
        assert drills[0]["lens"] == "parmenides"
        assert drills[0]["seed"] == "Which timeout applies?"
        assert drills[1]["lens"] == "philebus"

    def test_cap_enforced_and_no_duplicate_targets(self):
        findings = [
            {"verdict": "UNANSWERABLE", "support": 2,
             "question": "Who may edit?", "target": "AC-017"},
        ]
        drills = auto.select_drills(findings, ["AC-017", "NFR-002", "ERR-004"],
                                    cap=2)
        assert len(drills) == 2
        assert [d["target"] for d in drills] == ["AC-017", "NFR-002"]


class TestDossier:
    def test_fix_ready_ordering_and_warnings(self):
        ctx = {
            "spec_path": "specs/x/spec.md", "profile": "deep",
            "run_date": "2026-07-20",
            "models": {"dialogue": "claude --model claude-sonnet-5",
                       "measure": "(cli default)"},
            "tiers": [
                {"tier": "v2", "status": "ok"},
                {"tier": "v3", "status": "failed", "exit_code": 3},
            ],
            "stable_findings": [
                {"verdict": "CONTRADICTED", "support": 3,
                 "question": "Which timeout applies?", "target": "FR-011"},
                {"verdict": "UNANSWERABLE", "support": 2,
                 "question": "Who may rerun?", "target": "AC-003"},
            ],
            "measurement": None,
            "drills": [
                {"lens": "parmenides", "target": "FR-011",
                 "seed": "Which timeout applies?",
                 "terminal_state": "APORIA_CONTRADICTED", "turns": 2},
            ],
            "jgraph": None,
            "stable_low": ["NFR-002"],
        }
        text = auto.render_dossier(ctx)
        assert "Fix-ready summary" in text
        aporia = text.index("APORIA_CONTRADICTED")
        contradicted = text.index("[CONTRADICTED] FR-011")
        unanswerable = text.index("[UNANSWERABLE] AC-003")
        low = text.index("NFR-002")
        assert aporia < contradicted < unanswerable < low
        assert "v3" in text and "failed" in text


def _q(qid, question, target):
    return {"id": qid, "question": question, "target": target,
            "lines": [1], "category": "ambiguity"}


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
    "- **AC-003**: a completed challenge may be rerun by the operator.",
])


class TestScenario:
    def test_lite_e2e_with_replay_stub(self, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        stub = _replay_stub(tmp_path, [
            json.dumps({"questions": [
                _q("Q1", "Who may edit a locked row?", "FR-001")]}),
            json.dumps({"answers": [
                {"id": "Q1", "verdict": "UNANSWERABLE",
                 "answer": "The text does not say.", "evidence_lines": []}]}),
        ])
        rc = auto.main([str(spec), "--profile", "lite",
                        "--model-cmd", shlex.quote(stub)])
        assert rc == 0
        dossier = (tmp_path / "sue-dossier.md").read_text()
        assert "lite" in dossier
        assert (tmp_path / "sue-dossier.json").exists()
        assert (tmp_path / "socratic-challenge.md").exists()
        capsys.readouterr()

    def _fake_tools(self, monkeypatch, tmp_path, v2_rc=0, v3_rc=0):
        calls = {"dial": []}

        def fake_v2(argv):
            if v2_rc == 0:
                (tmp_path / "socratic-consensus.md").write_text(_V2_REPORT)
            return v2_rc

        def fake_v3(argv):
            if v3_rc == 0:
                (tmp_path / "semantic-reproducibility.json").write_text(
                    json.dumps({
                        "semantic_reproducibility": 0.42,
                        "per_requirement": {"NFR-002": {"score": 0.1}},
                        "stability": {
                            "sr_mean": 0.41, "sr_stdev": 0.01,
                            "extraction_noise_floor": 0.09,
                            "stable_low": ["NFR-002"],
                            "per_requirement": {}},
                    }))
            return v3_rc

        def fake_dial(argv):
            calls["dial"].append(list(argv))
            lens = argv[argv.index("--lens") + 1]
            target = argv[argv.index("--target") + 1]
            (tmp_path / "socratic-dialogue.json").write_text(json.dumps({
                "lens": lens, "target": target, "seed": "s",
                "terminal_state": "APORIA_UNDEFINED",
                "turns": [{"turn": 1, "operator": "DEFINE",
                           "verdict": "SILENT"}],
            }))
            return 0

        monkeypatch.setattr(auto.v2, "main", fake_v2)
        monkeypatch.setattr(auto.v3, "main", fake_v3)
        monkeypatch.setattr(auto.dial, "main", fake_dial)
        return calls

    def test_deep_orchestration_aggregates_all_sources(
            self, monkeypatch, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        calls = self._fake_tools(monkeypatch, tmp_path)
        rc = auto.main([str(spec), "--profile", "deep"])
        assert rc == 0
        data = json.loads((tmp_path / "sue-dossier.json").read_text())
        assert [f["target"] for f in data["stable_findings"]] == [
            "FR-011", "AC-003"]
        # drills: 2 findings + stable-low fill up to cap 3
        assert [d["target"] for d in data["drills"]] == [
            "FR-011", "AC-003", "NFR-002"]
        assert all(d["terminal_state"] == "APORIA_UNDEFINED"
                   for d in data["drills"])
        assert len(calls["dial"]) == 3
        capsys.readouterr()

    def test_v2_failure_degrades_but_dossier_written(
            self, monkeypatch, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        self._fake_tools(monkeypatch, tmp_path, v2_rc=3)
        rc = auto.main([str(spec), "--profile", "deep"])
        assert rc == 0
        data = json.loads((tmp_path / "sue-dossier.json").read_text())
        tiers = {t["tier"]: t["status"] for t in data["tiers"]}
        assert tiers["v2"] == "failed"
        assert tiers["v3"] == "ok"
        # drills fall back to v3 stable-low only
        assert [d["target"] for d in data["drills"]] == ["NFR-002"]
        capsys.readouterr()

    def test_all_tiers_failing_propagates_exit_code(
            self, monkeypatch, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        self._fake_tools(monkeypatch, tmp_path, v2_rc=3, v3_rc=3)
        rc = auto.main([str(spec), "--profile", "deep"])
        assert rc == 3
        capsys.readouterr()

    def test_collision_guard(self, tmp_path, capsys):
        spec = tmp_path / "sue-dossier.md"
        spec.write_text("previous\n")
        rc = auto.main([str(spec)])
        assert rc == 1
        assert spec.read_text() == "previous\n"
        capsys.readouterr()
