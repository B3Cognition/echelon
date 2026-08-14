"""Provider-free Understanding analysis service.

This module owns deterministic analysis and gate evaluation. Callers own
configuration discovery, evidence persistence, and presentation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from kernel.quality_gates import evaluate_quality_thresholds

from .constraint_metrics import ConstraintAnalyzer
from .requirement_projection import RequirementProjection, project_requirements
from .role_detection import detect_requirement_roles
from .semantic_metrics import SemanticAnalyzer, classify_ears_pattern


DEFAULT_QUALITY_GATES: dict[str, float] = {
    "overall": 0.75,
    "structure": 0.75,
    "testability": 0.75,
    "semantic": 0.65,
    "cognitive": 0.65,
    "readability": 0.55,
    "depth": 0.40,
    "behavioral": 0.55,
}


@dataclass(frozen=True)
class UnderstandingBundle:
    """Serializable result of one completed Understanding analysis."""

    analysis: dict[str, object]
    thresholds: dict[str, float]
    scores: dict[str, float]
    gates: dict[str, dict[str, object]]
    passed: bool
    requirement_count: int
    per_requirement: tuple[dict[str, object], ...]
    findings: tuple[dict[str, str], ...]
    diagrams: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "analysis": self.analysis,
            "thresholds": dict(self.thresholds),
            "scores": dict(self.scores),
            "gates": {name: dict(gate) for name, gate in self.gates.items()},
            "pass": self.passed,
            "requirement_count": self.requirement_count,
            "per_requirement": list(self.per_requirement),
            "entity_analysis": self.analysis.get("entity_analysis", {}),
            "behavioral_analysis": self.analysis.get("behavioral_analysis", {}),
            "findings": list(self.findings),
            "diagrams": dict(self.diagrams),
        }


def parse_requirements(spec_text: str) -> dict[str, object]:
    """Return the legacy dictionary view of canonical requirement objects."""
    projections = project_requirements(spec_text)
    requirements = [
        {"id": projection.requirement_id, "text": projection.normative_text}
        for projection in projections
    ]
    return {
        "requirements": requirements,
        "full_spec": spec_text,
        "count": len(requirements),
    }


def _projected_scoring_text(projections: tuple[RequirementProjection, ...]) -> str:
    return "\n".join(
        f"- **{projection.requirement_id}**: {projection.normative_text}"
        for projection in projections
    )


def _testability_text(projections: tuple[RequirementProjection, ...]) -> str:
    return "\n".join(_testability_requirements(projections))


def _testability_requirements(
    projections: tuple[RequirementProjection, ...],
) -> list[str]:
    return [
        " ".join((projection.normative_text, *projection.constraints)).strip()
        for projection in projections
    ]


def _depth_text(projections: tuple[RequirementProjection, ...]) -> str:
    return "\n".join(_depth_requirements(projections))


def _depth_requirements(projections: tuple[RequirementProjection, ...]) -> list[str]:
    known_ids = {projection.requirement_id for projection in projections}
    return [
        f"- **{projection.requirement_id}**: {' '.join(reference for reference in projection.traceability_references if reference in known_ids)}"
        for projection in projections
    ]


def _replace_category_metrics(
    destination: dict[str, object], source: dict[str, object], category: str
) -> None:
    """Replace one independently calculated metric family in an analysis."""
    destination_metrics = destination.get("metrics")
    source_metrics = source.get("metrics")
    if not isinstance(destination_metrics, dict) or not isinstance(source_metrics, dict):
        return
    destination_categories = destination_metrics.get("category_averages")
    source_categories = source_metrics.get("category_averages")
    if isinstance(destination_categories, dict) and isinstance(source_categories, dict):
        destination_categories[category] = source_categories.get(category, 0.0)
    destination_scores = destination_metrics.get("scores")
    source_scores = source_metrics.get("scores")
    if isinstance(destination_scores, list) and isinstance(source_scores, list):
        destination_metrics["scores"] = [
            score for score in destination_scores if isinstance(score, dict) and score.get("category") != category
        ] + [
            score for score in source_scores if isinstance(score, dict) and score.get("category") == category
        ]
    if isinstance(destination_metrics.get("scores"), list):
        destination_metrics["overall_weighted_average"] = sum(
            float(score.get("score", 0.0)) * float(score.get("weight", 0.0))
            for score in destination_metrics["scores"]
            if isinstance(score, dict)
        )


def analyze_text(
    text: str,
    *,
    enhanced: bool = True,
    use_nlp: bool = False,
    extract_entities: bool = False,
    use_energy: bool = False,
    metric_requirements: list[str] | None = None,
) -> dict[str, object]:
    """Analyze text without reading configuration or writing files."""
    if enhanced:
        from .enhanced_metrics import analyze_with_enhanced_metrics

        result = analyze_with_enhanced_metrics(
            text,
            use_spacy=use_nlp,
            metric_requirements=metric_requirements,
        )
        metrics = result["enhanced_metrics"]
        metric_count = result.get("metric_count", {})
    else:
        from .normalized_metrics import analyze_with_normalized_metrics

        result = analyze_with_normalized_metrics(
            text, metric_requirements=metric_requirements
        )
        metrics = result["normalized_metrics"]
        metric_count = {"total": len(metrics["scores"])}

    analysis: dict[str, object] = {
        "enhanced": enhanced,
        "metrics": metrics,
        "metric_count": metric_count,
    }
    if enhanced:
        analysis["behavioral_analysis"] = {
            "transitions": result.get("behavioral_transitions", []),
        }
        analysis["depth_analysis"] = {
            "dependency_graph": result.get("dependency_graph", {}),
        }

    if use_energy:
        from .energy_metrics import analyze_energy

        analysis["energy"] = analyze_energy(text).to_dict()

    if extract_entities:
        try:
            sentences = re.split(r"[.!?]+", text)
            requirements = [sentence.strip() for sentence in sentences if len(sentence.strip()) > 10]
            entity_result = SemanticAnalyzer(use_spacy=use_nlp).extract_entities_detailed(
                requirements,
                use_nlp=use_nlp,
            )
            analysis["entity_analysis"] = {
                "entities": [
                    {
                        "text": entity.text,
                        "type": entity.type.value,
                        "normalized": entity.normalized,
                        "requirement_id": entity.requirement_id,
                        "confidence": entity.confidence,
                    }
                    for entity in entity_result.entities
                ],
                "relationships": [
                    {
                        "source": {
                            "text": relationship.source.text,
                            "type": relationship.source.type.value,
                            "normalized": relationship.source.normalized,
                        },
                        "relation": relationship.relation,
                        "target": {
                            "text": relationship.target.text,
                            "type": relationship.target.type.value,
                            "normalized": relationship.target.normalized,
                        },
                        "requirement_id": relationship.requirement_id,
                    }
                    for relationship in entity_result.relationships
                ],
                "summary": {
                    "total_entities": len(entity_result.entities),
                    "unique_actors": len(entity_result.unique_actors),
                    "unique_actions": len(entity_result.unique_actions),
                    "unique_objects": len(entity_result.unique_objects),
                    "entity_counts": {
                        key.value: value
                        for key, value in entity_result.entity_counts.items()
                    },
                },
            }
        except (ImportError, AttributeError):
            pass
    return analysis


def analyze_spec(
    spec_path: Path,
    *,
    enhanced: bool = True,
    use_nlp: bool = False,
    extract_entities: bool = False,
    use_energy: bool = False,
) -> dict[str, object]:
    """Analyze one specification file."""
    analysis = analyze_text(
        spec_path.read_text(encoding="utf-8"),
        enhanced=enhanced,
        use_nlp=use_nlp,
        extract_entities=extract_entities,
        use_energy=use_energy,
    )
    analysis["spec_path"] = str(spec_path)
    analysis["spec_name"] = (
        spec_path.parent.name
        if spec_path.stem.lower() in {"spec", "requirements", "req"}
        else spec_path.stem
    )
    return analysis


def evaluate_quality_gates(
    metrics: Mapping[str, object],
    thresholds: Mapping[str, float],
) -> tuple[dict[str, float], dict[str, dict[str, object]], bool]:
    """Project configured metric values into explicit gate verdicts."""
    categories = metrics.get("category_averages", {})
    if not isinstance(categories, Mapping):
        categories = {}
    scores: dict[str, float] = {}
    for name, threshold in thresholds.items():
        raw_score = (
            metrics.get("overall_weighted_average", 0.0)
            if name == "overall"
            else categories.get(name, 0.0)
        )
        score = float(raw_score or 0.0)
        scores[name] = score
    decision = evaluate_quality_thresholds(scores, thresholds)
    gates: dict[str, dict[str, object]] = {}
    for name, threshold in decision.thresholds.items():
        score = scores[name]
        gates[name] = {
            "score": score,
            "threshold": threshold,
            "pass": decision.effective_passes[name],
        }
        if name == "overall":
            gates[name]["numeric_pass"] = decision.numeric_passes[name]
            gates[name]["pass_basis"] = decision.overall_pass_basis
    return scores, gates, decision.passed


def analyze_spec_bundle(
    spec_path: Path,
    *,
    thresholds: Mapping[str, float],
    enhanced: bool = True,
    use_nlp: bool = True,
    use_energy: bool = False,
    diagrams_enabled: bool = False,
    diagram_output_dir: Path | None = None,
) -> UnderstandingBundle:
    """Run complete deterministic analysis for the harness or CLI."""
    spec_text = spec_path.read_text(encoding="utf-8")
    projections = project_requirements(spec_text)
    requirements = [
        {"id": projection.requirement_id, "text": projection.normative_text}
        for projection in projections
    ]

    # Quality gates measure the formal requirements, not the surrounding
    # narrative.  A normal spec contains headings, rationale, architecture
    # notes, tables, and examples; feeding all of that to the metric engine
    # makes prose length and incidental words determine whether a requirement
    # passes.  The per-requirement report already uses this parsed source, so
    # the aggregate gate must use the same canonical requirement set.
    scoring_text = spec_text
    scoring_basis = "full_spec_fallback"
    if projections:
        scoring_text = _projected_scoring_text(projections)
        scoring_basis = "formal_requirements"
    analysis = analyze_text(
        scoring_text,
        enhanced=enhanced,
        use_nlp=use_nlp,
        extract_entities=enhanced,
        use_energy=use_energy,
        metric_requirements=[projection.normative_text for projection in projections]
        if projections
        else None,
    )
    analysis["spec_path"] = str(spec_path)
    analysis["spec_name"] = (
        spec_path.parent.name
        if spec_path.stem.lower() in {"spec", "requirements", "req"}
        else spec_path.stem
    )
    analysis["scoring_basis"] = scoring_basis
    if projections and enhanced:
        # Different metric families consume deliberately separate evidence:
        # constraints are testability-only and relationship metadata is
        # depth-only.  All prose-quality families continue to see normative
        # text exclusively.
        testability_analysis = analyze_text(
            _testability_text(projections),
            enhanced=True,
            use_nlp=use_nlp,
            metric_requirements=_testability_requirements(projections),
        )
        depth_analysis = analyze_text(
            _depth_text(projections),
            enhanced=True,
            use_nlp=use_nlp,
            metric_requirements=_depth_requirements(projections),
        )
        _replace_category_metrics(analysis, testability_analysis, "testability")
        _replace_category_metrics(analysis, depth_analysis, "depth")
        analysis["depth_analysis"] = depth_analysis.get("depth_analysis", {})
    per_requirement: list[dict[str, object]] = []
    semantic_analyzer = SemanticAnalyzer(use_spacy=use_nlp)
    constraint_analyzer = ConstraintAnalyzer()
    for projection in projections:
        requirement_text = projection.normative_text
        testability_input = " ".join((requirement_text, *projection.constraints)).strip()
        shared_roles = detect_requirement_roles(requirement_text)
        item = analyze_text(
            requirement_text,
            enhanced=enhanced,
            use_nlp=use_nlp,
            extract_entities=enhanced,
            use_energy=use_energy,
            metric_requirements=[requirement_text],
        )
        if enhanced:
            testability_item = analyze_text(
                testability_input,
                enhanced=True,
                use_nlp=use_nlp,
                metric_requirements=[testability_input],
            )
            _replace_category_metrics(item, testability_item, "testability")
        item.update(
            {
                "requirement_id": projection.requirement_id,
                "requirement_text": requirement_text,
                "original_text": projection.original_text,
                "normative_text": projection.normative_text,
                "constraints": list(projection.constraints),
                "traceability_references": list(projection.traceability_references),
                "source_location": {
                    "line_start": projection.source_location.line_start,
                    "line_end": projection.source_location.line_end,
                },
                "ears_pattern": classify_ears_pattern(requirement_text),
                "semantic_roles": semantic_analyzer.extract_roles_as_dict(
                    requirement_text
                ),
                "shared_roles": {
                    "actor": shared_roles.actor,
                    "action": shared_roles.action,
                    "object": shared_roles.object,
                    "detector_evidence": list(shared_roles.detector_evidence),
                },
                "detector_evidence": list(shared_roles.detector_evidence),
                "constraint_diagnostics": constraint_analyzer.diagnose_requirement(testability_input),
            }
        )
        per_requirement.append(item)

    scores, gates, passed = evaluate_quality_gates(
        analysis["metrics"],  # type: ignore[arg-type]
        thresholds,
    )
    findings: list[dict[str, str]] = []
    if not requirements:
        passed = False
        findings.append(
            {
                "code": "zero-requirements",
                "severity": "error",
                "message": "No formal requirements were parsed from spec.md.",
            }
        )
    diagrams: dict[str, object] = {
        "enabled": bool(diagrams_enabled),
        "status": "skipped",
        "outputs": [],
    }
    if diagrams_enabled:
        output_dir = diagram_output_dir or spec_path.parent / "understanding-diagrams"
        try:
            outputs = _generate_diagrams(spec_text, output_dir, use_nlp=use_nlp)
            diagrams.update(
                status="written",
                outputs=[str(path) for path in outputs],
            )
        except Exception as exc:
            diagrams.update(status="failed", error=str(exc))
            findings.append(
                {
                    "code": "diagram-generation-failed",
                    "severity": "warning",
                    "message": str(exc),
                }
            )
    return UnderstandingBundle(
        analysis=analysis,
        thresholds={name: float(value) for name, value in thresholds.items()},
        scores=scores,
        gates=gates,
        passed=passed,
        requirement_count=len(projections),
        per_requirement=tuple(per_requirement),
        findings=tuple(findings),
        diagrams=diagrams,
    )


def _generate_diagrams(
    spec_text: str,
    output_dir: Path,
    *,
    use_nlp: bool,
) -> list[Path]:
    """Generate the standard SVG and PNG entity diagrams."""
    from .entity_metrics import EntityExtractor

    output_dir.mkdir(parents=True, exist_ok=True)
    extractor = EntityExtractor(use_spacy=use_nlp)
    parsed = parse_requirements(spec_text)
    entities = []
    relationships = []
    for requirement in parsed["requirements"]:  # type: ignore[index]
        extracted = extractor.extract(
            str(requirement["text"]),
            requirement_id=str(requirement["id"]),
        )
        entities.extend(extracted.entities)
        relationships.extend(extracted.relationships)

    outputs: list[Path] = []
    base = output_dir / "entities"
    for format_name in ("svg", "png"):
        rendered = extractor.generate_graphviz_diagram(
            entities,
            relationships,
            output_path=str(base),
            fmt=format_name,
        )
        if not rendered:
            raise RuntimeError("Graphviz diagram rendering is unavailable")
        outputs.append(Path(rendered))
    return outputs
