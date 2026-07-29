"""Public, provider-free Understanding analysis service contracts."""

from pathlib import Path

import pytest

from understanding.service import (
    DEFAULT_QUALITY_GATES,
    analyze_spec_bundle,
    evaluate_quality_gates,
    parse_requirements,
)
import understanding.service as service


ALL_GATES = {
    "overall": 0.75,
    "structure": 0.75,
    "testability": 0.75,
    "semantic": 0.65,
    "cognitive": 0.65,
    "readability": 0.55,
    "depth": 0.40,
    "behavioral": 0.55,
}


@pytest.mark.unit
def test_evaluate_quality_gates_covers_every_configured_gate() -> None:
    metrics = {
        "overall_weighted_average": 0.90,
        "category_averages": {
            "structure": 0.90,
            "testability": 0.90,
            "semantic": 0.90,
            "cognitive": 0.90,
            "readability": 0.90,
            "depth": 0.39,
            "behavioral": 0.54,
        },
    }

    scores, gates, passed = evaluate_quality_gates(metrics, ALL_GATES)

    assert tuple(gates) == tuple(ALL_GATES)
    assert scores["depth"] == 0.39
    assert gates["depth"] == {"score": 0.39, "threshold": 0.40, "pass": False}
    assert gates["behavioral"]["pass"] is False
    assert passed is False


@pytest.mark.unit
def test_analyze_spec_bundle_is_serializable_and_reports_disabled_diagrams(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(
        "# Requirements\n\n"
        "- **FR-001**: The system SHALL store each submitted report.\n",
        encoding="utf-8",
    )

    bundle = analyze_spec_bundle(
        spec,
        thresholds=DEFAULT_QUALITY_GATES,
        enhanced=False,
        use_nlp=False,
        diagrams_enabled=False,
    )
    payload = bundle.to_dict()

    assert payload["requirement_count"] == 1
    assert payload["diagrams"] == {
        "enabled": False,
        "status": "skipped",
        "outputs": [],
    }
    assert set(payload["gates"]) == set(DEFAULT_QUALITY_GATES)
    assert isinstance(payload["pass"], bool)
    assert payload["analysis"]["spec_path"] == str(spec)
    assert payload["analysis"]["scoring_basis"] == "formal_requirements"


@pytest.mark.unit
def test_bundle_scores_formal_requirements_not_surrounding_narrative(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(
        "# Product rationale\n\n"
        "This deliberately verbose narrative is not a normative requirement. "
        "It may contain arbitrary vocabulary, examples, and implementation "
        "detail without changing the meaning of the formal requirement below.\n\n"
        "- **AC-001** (Error): Given an invalid request, when the user submits it, "
        "then the system SHALL return HTTP 400 with an observable error message.\n",
        encoding="utf-8",
    )

    bundle = analyze_spec_bundle(
        spec,
        thresholds=DEFAULT_QUALITY_GATES,
        enhanced=True,
        use_nlp=False,
    ).to_dict()

    assert bundle["requirement_count"] == 1
    assert bundle["analysis"]["scoring_basis"] == "formal_requirements"
    # The quality analysis must contain the criterion text, not the narrative.
    transitions = bundle["analysis"]["behavioral_analysis"]["transitions"]
    assert transitions


@pytest.mark.unit
def test_parse_requirements_accepts_parenthesized_criterion_classifier() -> None:
    parsed = parse_requirements(
        "- **AC-005** (Error): The system SHALL return a clear error.\n"
    )

    assert parsed["count"] == 1
    assert parsed["requirements"] == [
        {"id": "AC-005", "text": "The system SHALL return a clear error."}
    ]


@pytest.mark.unit
def test_parse_requirements_accepts_conventional_heading_statement_format() -> None:
    parsed = parse_requirements(
        "### FR-001: Store reports\n\n"
        "- **Statement**: The system SHALL store each submitted report.\n\n"
        "### NFR-001: Performance\n\n"
        "- **Statement**: The system SHALL respond within 200 ms.\n"
    )

    assert parsed["requirements"] == [
        {"id": "FR-001", "text": "The system SHALL store each submitted report."},
        {"id": "NFR-001", "text": "The system SHALL respond within 200 ms."},
    ]


@pytest.mark.unit
def test_zero_requirements_is_a_completed_deterministic_failure(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text("# Product note\n\nNo formal requirements yet.\n", encoding="utf-8")

    payload = analyze_spec_bundle(
        spec,
        thresholds=DEFAULT_QUALITY_GATES,
        enhanced=False,
        use_nlp=False,
    ).to_dict()

    assert payload["requirement_count"] == 0
    assert payload["pass"] is False
    assert payload["findings"] == [
        {
            "code": "zero-requirements",
            "severity": "error",
            "message": "No formal requirements were parsed from spec.md.",
        }
    ]


@pytest.mark.unit
def test_enabled_diagrams_report_written_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(
        "# Requirements\n\n- **FR-001**: The system SHALL store the report.\n",
        encoding="utf-8",
    )
    outputs = [tmp_path / "diagrams" / "entities.svg", tmp_path / "diagrams" / "entities.png"]
    monkeypatch.setattr(service, "_generate_diagrams", lambda *args, **kwargs: outputs)

    payload = analyze_spec_bundle(
        spec,
        thresholds=DEFAULT_QUALITY_GATES,
        enhanced=False,
        use_nlp=False,
        diagrams_enabled=True,
        diagram_output_dir=tmp_path / "diagrams",
    ).to_dict()

    assert payload["diagrams"] == {
        "enabled": True,
        "status": "written",
        "outputs": [str(path) for path in outputs],
    }


@pytest.mark.unit
def test_diagram_failure_is_recorded_without_aborting_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(
        "# Requirements\n\n- **FR-001**: The system SHALL store the report.\n",
        encoding="utf-8",
    )

    def fail(*args: object, **kwargs: object) -> list[Path]:
        raise RuntimeError("dot is unavailable")

    monkeypatch.setattr(service, "_generate_diagrams", fail)

    payload = analyze_spec_bundle(
        spec,
        thresholds=DEFAULT_QUALITY_GATES,
        enhanced=False,
        use_nlp=False,
        diagrams_enabled=True,
        diagram_output_dir=tmp_path / "diagrams",
    ).to_dict()

    assert payload["diagrams"] == {
        "enabled": True,
        "status": "failed",
        "outputs": [],
        "error": "dot is unavailable",
    }
    assert any(
        finding["code"] == "diagram-generation-failed"
        for finding in payload["findings"]
    )
