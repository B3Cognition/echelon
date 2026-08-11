from understanding.constraint_metrics import ConstraintAnalyzer
from understanding.markdown_parser import extract_requirements


def test_symbolic_numeric_equality_is_a_hard_constraint() -> None:
    analyzer = ConstraintAnalyzer()

    assert analyzer.count_hard_constraints("result_count = 0") == 1


def test_natural_language_numeric_equality_is_a_hard_constraint() -> None:
    analyzer = ConstraintAnalyzer()

    assert analyzer.count_hard_constraints("result count equals 0") == 1
    assert analyzer.count_hard_constraints("error rate equals 0.5") == 1
    assert analyzer.count_hard_constraints("error rate equal to 0.5") == 1
    assert analyzer.count_soft_constraints("result count equals 0") == 0


def test_explicit_must_not_contributes_negative_space_evidence() -> None:
    analyzer = ConstraintAnalyzer()

    metrics = analyzer.analyze_requirements(
        ["The system MUST NOT expose records outside the authorized scope."]
    )

    assert analyzer.count_negative_statements(
        "The system MUST NOT expose records outside the authorized scope."
    ) == 1
    assert metrics.negative_space_coverage > 0


def test_rich_spec_constraint_is_visible_on_the_id_bearing_line() -> None:
    requirements = extract_requirements(
        """
- **FR-001**: The system MUST return no unmatched records. Constraint: `result_count = 0`.
  - **Constraint:** `retry_count = 1`.
"""
    )

    assert len(requirements) == 1
    assert ConstraintAnalyzer().count_hard_constraints(requirements[0]) == 1
