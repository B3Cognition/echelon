"""Provider-free Understanding analysis service.

This module owns deterministic analysis and gate evaluation. Callers own
configuration discovery, evidence persistence, and presentation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .constraint_metrics import ConstraintAnalyzer
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
    """Parse formal requirements from Lexicon or conventional Markdown specs."""
    from .markdown_parser import extract_lexicon_requirements, is_lexicon_spec

    if is_lexicon_spec(spec_text):
        requirements = [
            {"id": requirement_id, "text": text}
            for requirement_id, text in extract_lexicon_requirements(spec_text)
        ]
    else:
        pattern = re.compile(r"^- \*\*([A-Z]{1,5}-\d{3,4})\*\*:(.+)$")
        requirements = []
        for line in spec_text.splitlines():
            match = pattern.match(line.strip())
            if match:
                requirements.append(
                    {"id": match.group(1), "text": match.group(2).strip()}
                )
    return {
        "requirements": requirements,
        "full_spec": spec_text,
        "count": len(requirements),
    }


def analyze_text(
    text: str,
    *,
    enhanced: bool = True,
    use_nlp: bool = False,
    extract_entities: bool = False,
    use_energy: bool = False,
) -> dict[str, object]:
    """Analyze text without reading configuration or writing files."""
    if enhanced:
        from .enhanced_metrics import analyze_with_enhanced_metrics

        result = analyze_with_enhanced_metrics(text, use_spacy=use_nlp)
        metrics = result["enhanced_metrics"]
        metric_count = result.get("metric_count", {})
    else:
        from .normalized_metrics import analyze_with_normalized_metrics

        result = analyze_with_normalized_metrics(text)
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
    gates: dict[str, dict[str, object]] = {}
    for name, threshold in thresholds.items():
        raw_score = (
            metrics.get("overall_weighted_average", 0.0)
            if name == "overall"
            else categories.get(name, 0.0)
        )
        score = float(raw_score or 0.0)
        required = float(threshold)
        scores[name] = score
        gates[name] = {
            "score": score,
            "threshold": required,
            "pass": score >= required,
        }
    return scores, gates, all(bool(gate["pass"]) for gate in gates.values())


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
    parsed = parse_requirements(spec_text)
    requirements = parsed["requirements"]
    assert isinstance(requirements, list)

    analysis = analyze_spec(
        spec_path,
        enhanced=enhanced,
        use_nlp=use_nlp,
        extract_entities=enhanced,
        use_energy=use_energy,
    )
    per_requirement: list[dict[str, object]] = []
    semantic_analyzer = SemanticAnalyzer(use_spacy=use_nlp)
    constraint_analyzer = ConstraintAnalyzer()
    for requirement in requirements:
        requirement_text = str(requirement["text"])
        item = analyze_text(
            requirement_text,
            enhanced=enhanced,
            use_nlp=use_nlp,
            extract_entities=enhanced,
            use_energy=use_energy,
        )
        item.update(
            {
                "requirement_id": str(requirement["id"]),
                "requirement_text": requirement_text,
                "ears_pattern": classify_ears_pattern(requirement_text),
                "semantic_roles": semantic_analyzer.extract_roles_as_dict(
                    requirement_text
                ),
                "constraint_diagnostics": constraint_analyzer.diagnose_requirement(
                    requirement_text
                ),
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
        requirement_count=len(requirements),
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
