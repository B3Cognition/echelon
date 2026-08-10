from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "runtime" / "templates"


@pytest.mark.parametrize(
    ("filename", "anchors"),
    [
        ("confidence-flags-template.md", ["## Confidence Flags", "| Artifact | Domains | Confidence | Correction Applied | Risk | Action |"]),
        ("experiment-results-template.md", ["## Experiment", "| Metric | Expected | Observed | Sample Size | Result |"]),
        ("evolution-report-template.md", ["## Run Comparison", "| Artifact | Change | Evidence | Quality Impact |"]),
        ("improvement-metrics-template.md", ["## Quality Trajectory", "| Run | Overall | Structure | Readability | Cognitive | Semantic | Testability | Behavioral | Depth |"]),
        ("stagnation-flags-template.md", ["## Stagnation Signals", "| Signal | Evidence | Duration | Impact | Recommended Experiment |"]),
        ("regression-alerts-template.md", ["## Regression Alerts", "| Area | Previous | Current | Delta | Severity | Probable Cause | Owner |"]),
        ("bias-check-template.md", ["## Bias Findings", "| Finding | Evidence | Risk | Counter-Evidence Sought | Recommendation |"]),
        ("constitution-amendment-candidates-template.md", ["## Candidate Register", "| ID | Proposed Principle | Source | Evidence | Confidence | Status |"]),
        ("feedback-report-template.md", ["## Effort Accuracy", "## Critical Findings", "| ID | Type | Severity | Finding | Recommended Expert |"]),
        ("drift-escalation-template.md", ["## Drift Summary", "## Required Human Decision", "| Divergence | Expected | Observed | Impact | Evidence |"]),
        ("evolution-signals-review-template.md", ["## Signal Review", "| ID | Trigger | Severity | Metrics | Failure Analysis | Status |"]),
        ("prompt-version-observations-template.md", ["## Observations", "| Agent | Domain | Prompt Version | Accuracy Signal | Downstream Outcome | Evidence |"]),
        ("calibration-analytics-template.md", ["## Domain Accuracy Analysis", "| Domain | Samples | Accuracy | Correction Factor | Trend | Confidence |"]),
    ],
)
def test_learning_artifact_templates_have_required_structure(
    filename: str, anchors: list[str]
) -> None:
    text = (TEMPLATE_DIR / filename).read_text(encoding="utf-8")

    for anchor in anchors:
        assert anchor in text


@pytest.mark.parametrize(
    ("source", "template"),
    [
        ("prosaic/subagents/echelon.auditor.md", "confidence-flags-template.md"),
        ("prosaic/subagents/echelon.investigator.md", "experiment-results-template.md"),
        ("prosaic/subagents/echelon.adaptive.md", "evolution-report-template.md"),
        ("prosaic/subagents/echelon.adaptive.md", "improvement-metrics-template.md"),
        ("prosaic/subagents/echelon.adaptive.md", "stagnation-flags-template.md"),
        ("prosaic/subagents/echelon.adaptive.md", "regression-alerts-template.md"),
        ("prosaic/subagents/echelon.adaptive.md", "bias-check-template.md"),
        ("prosaic/subagents/echelon.architect.md", "constitution-amendment-candidates-template.md"),
        ("prosaic/subagents/echelon.auditor.md", "feedback-report-template.md"),
        ("runtime/workflow/phases/appendices/build-8-feedback-reference.md", "drift-escalation-template.md"),
        ("prosaic/subagents/echelon.auditor.md", "evolution-signals-review-template.md"),
        ("prosaic/subagents/echelon.auditor.md", "prompt-version-observations-template.md"),
        ("prosaic/subagents/echelon.auditor.md", "calibration-analytics-template.md"),
    ],
)
def test_each_learning_artifact_producer_references_its_template(
    source: str, template: str
) -> None:
    assert template in (ROOT / source).read_text(encoding="utf-8")


def test_experiment_results_reference_is_consistently_markdown() -> None:
    investigator = (ROOT / "prosaic/subagents/echelon.investigator.md").read_text(
        encoding="utf-8"
    )
    workflow = (ROOT / "runtime/workflow/definition.yaml").read_text(encoding="utf-8")

    assert 'artifact: "experiment-results.md"' in investigator
    assert "experiment-results.json" not in investigator
    assert "experiment-results.json" not in workflow
