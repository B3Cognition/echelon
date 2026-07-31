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

    def test_plan_budget_distinguishes_logical_calls_from_retry_attempts(self):
        budget = auto.plan_budget("forensic", unit_count=79)

        assert budget.logical_calls == 91
        assert budget.max_provider_attempts == 182

    def test_plan_budget_uses_the_effective_drill_override(self):
        default = auto.plan_budget("deep", unit_count=10)
        expanded = auto.plan_budget("deep", unit_count=10, drill_cap=9)

        assert expanded.logical_calls - default.logical_calls == 6 * 7
        assert expanded.max_provider_attempts == expanded.logical_calls * 2

    @pytest.mark.parametrize(
        ("tool", "extra"),
        [
            (auto.v2, []),
            (auto.jg, []),
            (auto.dial, ["--seed", "which rule applies?"]),
        ],
    )
    def test_non_v1_dialogue_tools_accept_codex_execution_profile(
            self, tool, extra):
        config, _options = tool.parse_args([
            "spec.md",
            *extra,
            "--model-cmd", "codex=codex",
            "--model", "gpt-5.6-luna",
            "--reasoning-effort", "low",
        ])

        assert config.model == "gpt-5.6-luna"
        assert config.reasoning_effort == "low"


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

    def test_distinct_findings_on_same_target_each_keep_their_own_drill(self):
        findings = [
            {"id": "V2-F001", "verdict": "UNANSWERABLE", "support": 3,
             "question": "Who owns the field?", "target": "FR-LOAD"},
            {"id": "V2-F002", "verdict": "UNANSWERABLE", "support": 2,
             "question": "When is the field committed?", "target": "FR-LOAD"},
        ]

        drills = auto.select_drills(findings, [], cap=2)

        assert [drill["source_id"] for drill in drills] == [
            "V2-F001", "V2-F002",
        ]
        assert [drill["target"] for drill in drills] == ["FR-LOAD", "FR-LOAD"]


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
        calls = {"v2": [], "v3": [], "jgraph": [], "dial": []}

        def fake_v2(argv):
            calls["v2"].append(list(argv))
            if v2_rc == 0:
                (tmp_path / "socratic-consensus.md").write_text(_V2_REPORT)
            return v2_rc

        def fake_v3(argv):
            calls["v3"].append(list(argv))
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

        def fake_jgraph(argv):
            calls["jgraph"].append(list(argv))
            (tmp_path / auto.jg.JSON_FILENAME).write_text(json.dumps({
                "convergence": {
                    "consensus_conflicts": 0,
                    "distinct_conflicts": 0,
                    "unanimous_conflicts": 0,
                    "mean_evidence_completeness": 1.0,
                },
            }))
            return 0

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
        monkeypatch.setattr(auto.jg, "main", fake_jgraph)
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

    def test_call_estimate_counts_compound_and_dotted_bundle_units(
            self, monkeypatch, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(
            "- **AC-1.1** First criterion.\n"
            "- **FR-EL-001** Event log MUST render.\n"
            "- **NFR-COMPAT-002** Existing data MUST load.\n"
        )
        self._fake_tools(monkeypatch, tmp_path)

        rc = auto.main([str(spec), "--profile", "deep"])

        assert rc == 0
        assert "3 unit(s)" in capsys.readouterr().out

    def test_forensic_propagates_explicit_codex_profile_to_every_tier(
            self, monkeypatch, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        calls = self._fake_tools(monkeypatch, tmp_path)

        rc = auto.main([
            str(spec),
            "--profile", "forensic",
            "--model-cmd", "codex=codex",
            "--measure-model-cmd", "codex=codex",
            "--model", "gpt-5.6-luna",
            "--reasoning-effort", "low",
        ])

        assert rc == 0
        invoked = calls["v2"] + calls["v3"] + calls["jgraph"] + calls["dial"]
        assert invoked
        for argv in invoked:
            assert argv[argv.index("--model") + 1] == "gpt-5.6-luna"
            assert argv[argv.index("--reasoning-effort") + 1] == "low"
        dossier = json.loads((tmp_path / "sue-dossier.json").read_text())
        assert dossier["models"]["requested"] == "gpt-5.6-luna"
        assert dossier["models"]["reasoning_effort"] == "low"
        report = (tmp_path / "sue-dossier.md").read_text()
        assert "- **Requested model:** gpt-5.6-luna" in report
        assert "- **Reasoning effort:** low" in report
        capsys.readouterr()

    def test_v2_failure_fails_fast_and_returns_nonzero_with_dossier(
            self, monkeypatch, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        self._fake_tools(monkeypatch, tmp_path, v2_rc=3)
        rc = auto.main([str(spec), "--profile", "deep"])
        assert rc == 3
        data = json.loads((tmp_path / "sue-dossier.json").read_text())
        tiers = {t["tier"]: t["status"] for t in data["tiers"]}
        assert tiers["v2"] == "failed"
        assert tiers["v3"] == "not_run"
        assert tiers["drills"] == "not_run"
        assert data["drills"] == []
        capsys.readouterr()

    def test_continue_and_allow_partial_are_explicit_opt_ins(
            self, monkeypatch, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        calls = self._fake_tools(monkeypatch, tmp_path, v2_rc=3)

        rc = auto.main([
            str(spec), "--profile", "deep",
            "--continue-on-tier-failure", "--allow-partial",
        ])

        assert rc == 0
        assert calls["v3"]
        data = json.loads((tmp_path / "sue-dossier.json").read_text())
        assert {tier["tier"]: tier["status"] for tier in data["tiers"]} == {
            "v2": "failed", "v3": "ok", "drills": "ok",
        }
        capsys.readouterr()

    def test_v3_failure_reports_measurement_unavailable_not_zero_stable_low(
            self, monkeypatch, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        self._fake_tools(monkeypatch, tmp_path, v3_rc=3)

        rc = auto.main([str(spec), "--profile", "deep"])

        assert rc == 3
        output = capsys.readouterr().out
        assert "stable-low N/A" in output
        report = (tmp_path / "sue-dossier.md").read_text()
        assert "v3 measurement unavailable" in report.lower()

    def test_provider_attempt_budget_rejects_plan_before_any_tier(
            self, monkeypatch, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        calls = self._fake_tools(monkeypatch, tmp_path)

        rc = auto.main([
            str(spec), "--profile", "forensic",
            "--max-provider-attempts", "10",
        ])

        assert rc == 1
        assert not any(calls.values())
        assert "requires up to" in capsys.readouterr().err

    def test_each_drill_is_archived_under_a_unique_finding_artifact(
            self, monkeypatch, tmp_path, capsys):
        spec = tmp_path / "spec.md"
        spec.write_text(_SPEC + "\n")
        calls = self._fake_tools(monkeypatch, tmp_path)

        rc = auto.main([str(spec), "--profile", "deep"])

        assert rc == 0
        data = json.loads((tmp_path / "sue-dossier.json").read_text())
        refs = [drill["artifact_json"] for drill in data["drills"]]
        assert len(refs) == len(set(refs)) == len(calls["dial"])
        assert all((tmp_path / ref).is_file() for ref in refs)
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
