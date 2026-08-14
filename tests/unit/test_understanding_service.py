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
from harness.quality_scores import derive_quality_pass_from_thresholds


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
def test_all_category_gates_certify_borderline_aggregate() -> None:
    metrics = {
        "overall_weighted_average": 0.7354,
        "category_averages": {
            "structure": 0.75,
            "testability": 0.75,
            "semantic": 0.65,
            "cognitive": 0.65,
            "readability": 0.55,
            "depth": 0.40,
            "behavioral": 0.55,
        },
    }

    scores, gates, passed = evaluate_quality_gates(metrics, ALL_GATES)

    assert scores["overall"] == 0.7354
    assert gates["overall"]["numeric_pass"] is False
    assert gates["overall"]["pass"] is True
    assert gates["overall"]["pass_basis"] == "all_configured_categories_pass"
    assert passed is True
    assert derive_quality_pass_from_thresholds(scores, ALL_GATES) is True


@pytest.mark.unit
def test_overall_only_gate_remains_numerically_enforced() -> None:
    metrics = {
        "overall_weighted_average": 0.7354,
        "category_averages": {"structure": 1.0},
    }

    _scores, gates, passed = evaluate_quality_gates(metrics, {"overall": 0.75})

    assert gates["overall"]["pass"] is False
    assert passed is False
    assert derive_quality_pass_from_thresholds(
        {"overall": 0.7354}, {"overall": 0.75}
    ) is False


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
def test_parse_requirements_is_compatibility_view_of_canonical_projection() -> None:
    parsed = parse_requirements(
        "- **FR-001**: The command SHALL emit the result. "
        "Constraint: Exit status is zero. Verified by: AC-001.\n"
    )

    assert parsed["requirements"] == [
        {"id": "FR-001", "text": "The command SHALL emit the result."}
    ]


@pytest.mark.unit
def test_bundle_uses_shared_roles_for_semantic_gate_and_every_identifier_family(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(
        "- **FR-001**: The greeting command must write the configured message.\n"
        "- **AC-001**: No action is specified.\n",
        encoding="utf-8",
    )

    bundle = analyze_spec_bundle(
        spec,
        thresholds=DEFAULT_QUALITY_GATES,
        enhanced=True,
        use_nlp=False,
    ).to_dict()

    semantic_scores = {
        score["name"]: score["score"]
        for score in bundle["analysis"]["metrics"]["scores"]
        if score["category"] == "semantic"
    }
    assert bundle["requirement_count"] == 2
    assert semantic_scores["actor_presence"] == 0.5
    assert semantic_scores["action_presence"] == 0.5
    assert semantic_scores["object_presence"] == 0.5


@pytest.mark.unit
def test_bundle_keeps_constraints_in_one_testability_requirement_unit(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(
        "- **FR-001**: The greeting command must write the configured message. "
        "Constraint: output_length <= 128 bytes.\n",
        encoding="utf-8",
    )

    bundle = analyze_spec_bundle(
        spec,
        thresholds=DEFAULT_QUALITY_GATES,
        enhanced=True,
        use_nlp=False,
    ).to_dict()

    testability_scores = {
        score["name"]: score["raw_value"]
        for score in bundle["analysis"]["metrics"]["scores"]
        if score["category"] == "testability"
    }
    item_scores = {
        score["name"]: score["raw_value"]
        for score in bundle["per_requirement"][0]["metrics"]["scores"]
        if score["category"] == "testability"
    }
    assert testability_scores["constraint_density"] == pytest.approx(0.9975212478)
    assert item_scores["constraint_density"] == pytest.approx(0.9975212478)


@pytest.mark.unit
def test_bundle_depth_uses_generic_lexicon_ids_from_explicit_projection(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(
        "ARTIFACT: SPEC\n\n"
        "REQ: R1\n"
        "THEN: the greeting command MUST write a message\n"
        "DEPENDS: TASK-07\n\n"
        "REQ: TASK-07\n"
        "THEN: the greeting command MUST write an audit record\n",
        encoding="utf-8",
    )

    bundle = analyze_spec_bundle(
        spec,
        thresholds=DEFAULT_QUALITY_GATES,
        enhanced=True,
        use_nlp=False,
    ).to_dict()

    assert bundle["analysis"]["depth_analysis"]["dependency_graph"] == {
        "R1": ["TASK-07"],
        "TASK-07": [],
    }


@pytest.mark.unit
def test_direct_enhanced_depth_does_not_treat_technical_tokens_as_ids() -> None:
    from understanding.enhanced_metrics import analyze_with_enhanced_metrics

    result = analyze_with_enhanced_metrics(
        "FR-001: The command MUST store SHA256 and TLS1 values.",
        use_spacy=False,
    )

    assert result["dependency_graph"] == {"FR-001": []}


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
