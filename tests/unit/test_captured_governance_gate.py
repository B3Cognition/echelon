"""Captured Phase 2 governance uses native policy without live file authority."""
from pathlib import Path
import json

import pytest

from harness import governance_structural_gate as gate
from tests.unit.test_governance_structural_gate import (
    _governance, _write_governance_artifacts, _run, EXTENSION_ROOT,
)


FEASIBILITY = """## Metadata
Spec: game
## Feasibility Verdict
Feasible.
## Key Risks
No blocking risks.
## Kill / Defer / Pass Decision
Decision: PASS
"""
TEMPLATE = "## Metadata\n## Feasibility Verdict\n## Key Risks\n## Kill / Defer / Pass Decision\n"


def evaluate(root, **changes):
    function = getattr(gate, "evaluate_captured_governance_structural_gate", None)
    assert callable(function), "Managed Phase 2 requires captured, write-free structural evaluation"
    return function(**{**dict(artifact_key="feasibility", spec_dir=root / "specs",
        governance_config=_governance(), artifact_text=FEASIBILITY,
        reference_texts={}, template_text=TEMPLATE, previous_attempts=2,
        iteration=0, max_iterations=5), **changes})


@pytest.mark.parametrize("kind,ref", [("feasibility", None),
    ("intent-alignment-check", "FR-001"), ("intent-alignment-check", "FR-404")])
def test_captured_evaluation_has_no_live_input_or_report_io(tmp_path, monkeypatch, kind, ref):
    import lexicon.structural  # Load validator code before forbidding input I/O.
    from lexicon import parser
    from tests.unit.test_structural_validate import SPEC, _doc
    parser._parser.cache_clear()  # Exercise the bundled grammar's cold-load path.
    read_text = Path.read_text
    grammar_reads = []
    def forbidden(*args, **kwargs):
        pytest.fail("Captured structural evaluation must not access live files")
    def bundled_grammar_only(path, *args, **kwargs):
        if path != parser._GRAMMAR_PATH:
            forbidden()
        grammar_reads.append(path)
        return read_text(path, *args, **kwargs)
    changes = {} if ref is None else dict(artifact_key=kind, artifact_text=_doc(ref=ref),
        template_text="## Alignment Verdict\n", reference_texts={"spec.md": SPEC})
    with monkeypatch.context() as patch:
        for name in ("read_bytes", "write_text", "write_bytes", "resolve", "is_file", "is_dir"):
            patch.setattr(Path, name, forbidden)
        patch.setattr(Path, "read_text", bundled_grammar_only)
        patch.setattr(gate, "_write_json_atomic", forbidden)
        result, report = evaluate(tmp_path, **changes)
    if ref == "FR-404":
        assert result.action == "block" and result.passed is False and result.attempts == 3
        assert [item["code"] for item in report["findings"]] == ["unresolved-ref"]
    else:
        assert result.action == "proceed" and result.passed is True
        assert result.attempts == result.findings == 0
        assert report == dict(schema_version=1, artifact=kind,
            path=str(tmp_path / "specs" / (kind + ".md")), ok=True, findings=[])
    assert grammar_reads == ([] if ref is None else [parser._GRAMMAR_PATH])
    assert not (tmp_path / "specs").exists()


@pytest.mark.parametrize("captured", [False, True])
def test_passing_gate_does_not_consult_failure_only_budget(tmp_path, captured):
    config = _governance(max_repair_attempts=float("inf"))
    if captured:
        result, _ = evaluate(tmp_path, governance_config=config)
    else:
        result = _run(_write_governance_artifacts(tmp_path), config=config)
    assert result.action == "proceed" and result.attempts == 0


@pytest.mark.parametrize("kind", ["feasibility", "intent-alignment-check"])
@pytest.mark.parametrize("valid", [True, False])
def test_captured_and_native_evaluation_have_identical_report_and_policy(tmp_path, kind, valid):
    root = _write_governance_artifacts(tmp_path, **({"feasibility": "invalid"} if not valid and kind == "feasibility"
        else {"intent": "invalid"} if not valid else {}))
    config = _governance()
    entry = config["governance"]["artifacts"][kind]
    captured, report = evaluate(tmp_path, artifact_key=kind, spec_dir=root, governance_config=config,
        artifact_text=(root / (kind + ".md")).read_text(),
        reference_texts={"spec.md": (root / "spec.md").read_text()} if kind == "intent-alignment-check" else {},
        template_text=(EXTENSION_ROOT / "templates" / entry["template"]).read_text())
    assert not (root / (kind + "-structural-report.json")).exists()
    native = _run(root, artifact_key=kind, config=config, previous_attempts=2)
    assert native == captured
    assert json.loads(native.report_path.read_text()) == report
    assert captured.action == ("proceed" if valid else "block")
    assert captured.attempts == (0 if valid else 3)


@pytest.mark.parametrize("prior,policy,iteration,cap,want,attempts", [
    (0, "block", 0, 3, "repair", 1),
    (1, "block", 0, 3, "repair", 2),
    (2, "block", 0, 3, "block", 3),
    (2, "warn", 0, 3, "proceed_with_warning", 3),
    (0, "warn", 5, 99, "proceed_with_warning", 1),
    ("invalid", "block", 0, 3, "repair", 1),
])
def test_captured_failure_preserves_native_exhaustion_policy(tmp_path, prior, policy, iteration, cap, want, attempts):
    result, report = evaluate(tmp_path, artifact_text="# Incomplete\n", previous_attempts=prior,
        governance_config=_governance(on_exhausted=policy, max_repair_attempts=cap), iteration=iteration)
    assert result.action == want and result.attempts == attempts
    assert result.passed is False and report["ok"] is False
    assert result.exhausted_artifact == ("feasibility" if want in {"block", "proceed_with_warning"} else None)


@pytest.mark.parametrize("enabled,tier", [(False, "structural"), (True, "semantic")])
def test_bypassed_gate_does_not_require_captures_or_produce_report(tmp_path, enabled, tier):
    result, report = evaluate(tmp_path, governance_config=_governance(enabled=enabled, tier=tier),
        artifact_text=None, template_text=None)
    assert result.action == "proceed" and result.attempts == 0 and report is None


def test_absent_artifact_produces_native_missing_finding(tmp_path):
    result, report = evaluate(tmp_path, artifact_text=None, previous_attempts=0)
    assert result.action == "repair" and result.attempts == 1
    assert report["findings"] == [dict(code="missing-structural-artifact",
        message="required governance artifact is missing: feasibility.md", artifact="feasibility.md")]


def test_absent_template_blocks_without_certification_or_attempt_charge(tmp_path):
    result, report = evaluate(tmp_path, template_text=None)
    assert result.action == "block" and result.passed is False and result.attempts == 2
    assert result.blocked_reason == "governance_structural_capture_invalid" and report is None


def test_captured_template_controls_sections_not_live_template(tmp_path):
    result, report = evaluate(tmp_path, template_text=TEMPLATE + "## Captured requirement\n", previous_attempts=0)
    assert result.action == "repair"
    assert any(item["code"] == "missing-section" and item["span"] == "captured requirement" for item in report["findings"])


@pytest.mark.parametrize("references,expected", [({}, "block"), ({"spec.md": None}, "repair")])
def test_unselected_reference_is_not_the_same_as_captured_absence(tmp_path, references, expected):
    result, report = evaluate(tmp_path, artifact_key="intent-alignment-check", previous_attempts=0,
        artifact_text="## Alignment Verdict\nALIGNED\n", template_text="## Alignment Verdict\n",
        reference_texts=references)
    assert result.action == expected
    if report is None:
        assert result.attempts == 0 and result.blocked_reason == "governance_structural_capture_invalid"
    else:
        assert result.attempts == 1
        assert report["findings"][0]["code"] == "missing-cross-reference"


def test_reference_validation_uses_captured_source(tmp_path):
    from tests.unit.test_structural_validate import SPEC, _doc
    result, report = evaluate(tmp_path, artifact_key="intent-alignment-check", previous_attempts=0,
        artifact_text=_doc(ref="FR-404"), template_text="## Alignment Verdict\n",
        reference_texts={"spec.md": SPEC})
    assert result.action == "repair"
    assert any(item["code"] == "unresolved-ref" and item["span"] == "FR-404" for item in report["findings"])


@pytest.mark.parametrize("field,value", [("path", "../outside.md"), ("report", "/outside/report.json")])
def test_captured_paths_cannot_escape_selected_spec(tmp_path, field, value):
    config = _governance()
    config["governance"]["artifacts"]["feasibility"][field] = value
    result, report = evaluate(tmp_path, governance_config=config)
    assert result.action == "block" and result.attempts == 2 and report is None


@pytest.mark.parametrize("template", ["../outside.md", "/outside/template.md"])
def test_captured_template_text_does_not_authorize_escaped_template_selection(tmp_path, template):
    config = _governance()
    config["governance"]["artifacts"]["feasibility"]["template"] = template
    result, report = evaluate(tmp_path, governance_config=config)
    assert result.action == "block" and result.passed is False
    assert result.attempts == 2 and report is None


def test_validator_outage_is_a_native_failure_not_certification(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("validator unavailable")
    monkeypatch.setattr("lexicon.structural.structural_validate", broken)
    result, report = evaluate(tmp_path, previous_attempts=0)
    assert result.action == "repair" and result.attempts == 1
    assert report["findings"][0]["code"] == "structural-validator-error"
