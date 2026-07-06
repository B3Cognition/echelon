from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - dependency is present in test env
    yaml = None  # type: ignore[assignment]

from harness.stacks.detectors.re_artifacts import detect_re_artifacts
from harness.stacks.detectors.source_tree import detect_source_tree
from harness.stacks.errors import StackValidationError
from harness.stacks.evidence import StackEvidence, normalize_evidence_value
from harness.stacks.schema import StackDefinition, StackDetectionRuleSet


SCHEMA_VERSION = "1.0"
STRONG_MATCH_THRESHOLD = 0.85
PLAUSIBLE_MATCH_THRESHOLD = 0.60


@dataclass(frozen=True)
class StackDecision:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class DetectedStack:
    id: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    recommendation: str | None = None
    decision_required: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence,
        }
        if self.recommendation:
            payload["recommendation"] = self.recommendation
        if self.decision_required:
            payload["decision_required"] = self.decision_required
        return payload


@dataclass(frozen=True)
class StackDetectionReport:
    target: str
    evidence: list[StackEvidence]
    observed_stacks: list[DetectedStack]
    matching_echelon_stacks: list[DetectedStack]
    modernization_candidates: list[DetectedStack]
    decisions_required: list[StackDecision] = field(default_factory=list)
    suggested_config: dict[str, Any] | None = None
    status: str = "match"
    schema_version: str = SCHEMA_VERSION
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "target": self.target,
            "status": self.status,
            "evidence": [item.to_dict() for item in self.evidence],
            "observed_stacks": [stack.to_dict() for stack in self.observed_stacks],
            "matching_echelon_stacks": [
                stack.to_dict() for stack in self.matching_echelon_stacks
            ],
            "modernization_candidates": [
                stack.to_dict() for stack in self.modernization_candidates
            ],
            "decisions_required": [
                decision.to_dict() for decision in self.decisions_required
            ],
            "suggested_config": self.suggested_config,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class WrittenDetectionReport:
    run_dir: Path
    yaml_path: Path
    markdown_path: Path


def detect_stacks(
    *,
    target: Path,
    stack_definitions: dict[str, StackDefinition],
    artifact_roots: list[Path] | None = None,
) -> StackDetectionReport:
    target = target.resolve()
    evidence = [
        *detect_source_tree(target),
        *detect_re_artifacts([path.resolve() for path in artifact_roots or []]),
    ]
    decisions_required = _decisions_from_evidence(evidence)
    observed_stacks = _observed_stacks(evidence)
    matching, modernization = _score_echelon_stacks(
        evidence=evidence,
        definitions=stack_definitions,
        has_blocking_decisions=bool(decisions_required),
    )
    suggested_config = _suggested_config(matching, stack_definitions, decisions_required)
    status = "match" if observed_stacks or matching or modernization else "no_match"
    return StackDetectionReport(
        target=str(target),
        evidence=evidence,
        observed_stacks=observed_stacks,
        matching_echelon_stacks=matching,
        modernization_candidates=modernization,
        decisions_required=decisions_required,
        suggested_config=suggested_config,
        status=status,
    )


def detection_report_to_yaml(report: StackDetectionReport) -> str:
    if yaml is None:
        raise StackValidationError("PyYAML is required for stack detection reports")
    return yaml.safe_dump(report.to_dict(), sort_keys=False)


def detection_report_from_file(path: Path) -> StackDetectionReport:
    if yaml is None:
        raise StackValidationError("PyYAML is required for stack detection reports", path=path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return detection_report_from_dict(raw)


def detection_report_from_dict(raw: dict[str, Any]) -> StackDetectionReport:
    evidence = [
        StackEvidence(
            kind=str(item.get("kind", "")),
            value=str(item.get("value", "")),
            source=str(item.get("source", "")),
            location=str(item.get("location", "")),
            confidence=str(item.get("confidence", "high")),
        )
        for item in raw.get("evidence", [])
        if isinstance(item, dict)
    ]
    return StackDetectionReport(
        schema_version=str(raw.get("schema_version", SCHEMA_VERSION)),
        target=str(raw.get("target", "")),
        status=str(raw.get("status", "no_match")),
        evidence=evidence,
        observed_stacks=_detected_stacks_from_raw(raw.get("observed_stacks", [])),
        matching_echelon_stacks=_detected_stacks_from_raw(
            raw.get("matching_echelon_stacks", [])
        ),
        modernization_candidates=_detected_stacks_from_raw(
            raw.get("modernization_candidates", [])
        ),
        decisions_required=[
            StackDecision(
                code=str(item.get("code", "")),
                message=str(item.get("message", "")),
            )
            for item in raw.get("decisions_required", [])
            if isinstance(item, dict)
        ],
        suggested_config=raw.get("suggested_config"),
        warnings=[
            str(item)
            for item in raw.get("warnings", [])
            if str(item).strip()
        ],
    )


def render_detection_markdown(report: StackDetectionReport) -> str:
    lines = ["# Echelon Stack Detection", "", f"Target: `{report.target}`", ""]
    lines.extend(_render_stack_section("Observed stacks", report.observed_stacks))
    lines.extend(
        _render_stack_section("Matching Echelon stacks", report.matching_echelon_stacks)
    )
    lines.extend(
        _render_stack_section("Modernization candidates", report.modernization_candidates)
    )
    lines.extend(["## Decisions Required", ""])
    if report.decisions_required:
        for decision in report.decisions_required:
            lines.append(f"- {decision.code}: {decision.message}")
    else:
        lines.append("- None.")
    lines.extend(["", "## Suggested Config", ""])
    if report.suggested_config is None:
        lines.append("- None.")
    else:
        lines.append("```yaml")
        lines.append(yaml.safe_dump(report.suggested_config, sort_keys=False).rstrip())
        lines.append("```")
    return "\n".join(lines).rstrip() + "\n"


def write_detection_report(
    report: StackDetectionReport,
    *,
    project_root: Path,
    now: datetime | None = None,
) -> WrittenDetectionReport:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    run_dir = project_root / "runs" / "stack-detect" / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = run_dir / "detected.yml"
    markdown_path = run_dir / "detected.md"
    yaml_path.write_text(detection_report_to_yaml(report), encoding="utf-8")
    markdown_path.write_text(render_detection_markdown(report), encoding="utf-8")
    return WrittenDetectionReport(
        run_dir=run_dir,
        yaml_path=yaml_path,
        markdown_path=markdown_path,
    )


def _detected_stacks_from_raw(raw: Any) -> list[DetectedStack]:
    if not isinstance(raw, list):
        return []
    stacks: list[DetectedStack] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        stacks.append(
            DetectedStack(
                id=str(item.get("id", "")),
                confidence=float(item.get("confidence", 0.0) or 0.0),
                evidence=[str(value) for value in item.get("evidence", [])],
                recommendation=(
                    str(item["recommendation"]) if item.get("recommendation") else None
                ),
                decision_required=(
                    str(item["decision_required"])
                    if item.get("decision_required")
                    else None
                ),
            )
        )
    return stacks


def _decisions_from_evidence(evidence: list[StackEvidence]) -> list[StackDecision]:
    if any(item.kind == "decision" and item.value == "target-stack-unresolved" for item in evidence):
        return [
            StackDecision(
                code="TARGET_STACK_UNRESOLVED",
                message="RE artifacts explicitly mark target stack selection as requiring human input.",
            )
        ]
    return []


def _observed_stacks(evidence: list[StackEvidence]) -> list[DetectedStack]:
    values = _evidence_values_by_kind(evidence)
    observed: list[DetectedStack] = []

    def add(stack_id: str, confidence: float, required: set[str]) -> None:
        matched = _evidence_lines(evidence, kind="technology", values=required)
        observed.append(DetectedStack(id=stack_id, confidence=confidence, evidence=matched))

    technologies = values["technology"]
    dependencies = values["dependency"]
    if "playbook" in technologies or "@statsperform/react-playbook" in dependencies:
        add("playbook-design-system", 0.90, {"playbook"})
    if {"nextjs", "nx"}.issubset(technologies):
        add("nextjs-nx-webapp", 0.90, {"nextjs", "nx"})
    if "nestjs" in technologies:
        add("nestjs-api-service", 0.90, {"nestjs"})
    if "postgres" in technologies:
        add("postgres-data-store", 0.90, {"postgres"})
    if "dotnet" in technologies:
        add("legacy-dotnet-api", 0.85, {"dotnet"})
    if {"terraform", "argocd", "kubernetes"}.intersection(technologies):
        add(
            "terraform-argocd-kubernetes-delivery",
            0.80,
            {"terraform", "argocd", "kubernetes"}.intersection(technologies),
        )
    return sorted(observed, key=lambda stack: stack.id)


def _score_echelon_stacks(
    *,
    evidence: list[StackEvidence],
    definitions: dict[str, StackDefinition],
    has_blocking_decisions: bool,
) -> tuple[list[DetectedStack], list[DetectedStack]]:
    matching: list[DetectedStack] = []
    modernization: list[DetectedStack] = []
    for stack in definitions.values():
        negative_score, _ = _score_rules(stack.detection.negative, evidence)
        if negative_score > 0:
            continue

        positive_score, positive_evidence = _score_rules(stack.detection.positive, evidence)
        if positive_score >= STRONG_MATCH_THRESHOLD:
            recommendation = _recommendation_for_match(stack, has_blocking_decisions)
            matching.append(
                DetectedStack(
                    id=stack.id,
                    confidence=positive_score,
                    recommendation=recommendation,
                    evidence=positive_evidence,
                    decision_required=(
                        "Explicit confirmation required before adoption."
                        if recommendation != "adopt"
                        else None
                    ),
                )
            )

        modernization_score, modernization_evidence = _score_rules(
            stack.detection.modernization, evidence
        )
        if modernization_score >= PLAUSIBLE_MATCH_THRESHOLD:
            modernization.append(
                DetectedStack(
                    id=stack.id,
                    confidence=modernization_score,
                    recommendation="consider",
                    evidence=modernization_evidence,
                    decision_required="Modernization target requires explicit confirmation.",
                )
            )

    return (
        sorted(matching, key=lambda stack: stack.id),
        sorted(modernization, key=lambda stack: stack.id),
    )


def _recommendation_for_match(stack: StackDefinition, has_blocking_decisions: bool) -> str:
    if has_blocking_decisions:
        return "consider"
    if stack.kind == "capability":
        return "adopt"
    return "consider"


def _score_rules(
    rules: StackDetectionRuleSet,
    evidence: list[StackEvidence],
) -> tuple[float, list[str]]:
    categories = {
        "technology": rules.technologies,
        "dependency": rules.dependencies,
        "file": rules.files,
    }
    available_kinds = {item.kind for item in evidence}
    required_categories = {
        kind: {normalize_evidence_value(value) for value in values}
        for kind, values in categories.items()
        if values and (kind != "file" or "file" in available_kinds)
    }
    if not required_categories:
        return 0.0, []

    matched_categories = 0
    matched_lines: list[str] = []
    for kind, required_values in required_categories.items():
        lines = _evidence_lines(evidence, kind=kind, values=required_values)
        if not lines:
            continue
        matched_categories += 1
        matched_lines.extend(lines)

    return matched_categories / len(required_categories), _append_unique(matched_lines)


def _evidence_lines(
    evidence: list[StackEvidence],
    *,
    kind: str,
    values: set[str],
) -> list[str]:
    lines: list[str] = []
    for item in evidence:
        if item.kind != kind:
            continue
        if normalize_evidence_value(item.value) not in values:
            continue
        source = Path(item.source).name if item.source else "unknown"
        location = f": {item.location}" if item.location else ""
        lines.append(f"{source}{location} identifies {item.value}")
    return _append_unique(lines)


def _evidence_values_by_kind(evidence: list[StackEvidence]) -> dict[str, set[str]]:
    values = {"technology": set(), "dependency": set(), "file": set()}
    for item in evidence:
        if item.kind in values:
            values[item.kind].add(normalize_evidence_value(item.value))
    return values


def _suggested_config(
    matching: list[DetectedStack],
    definitions: dict[str, StackDefinition],
    decisions_required: list[StackDecision],
) -> dict[str, Any] | None:
    if decisions_required:
        return None
    selected = [
        stack.id
        for stack in matching
        if stack.recommendation == "adopt" and stack.confidence >= STRONG_MATCH_THRESHOLD
    ]
    if not selected:
        return None
    target_archetypes: list[str] = []
    for stack_id in selected:
        for archetype in definitions[stack_id].applies_to_archetypes:
            if archetype not in target_archetypes:
                target_archetypes.append(archetype)
    return {
        "stacks": {
            "selected": selected,
            "target_archetypes": target_archetypes,
        }
    }


def _render_stack_section(title: str, stacks: list[DetectedStack]) -> list[str]:
    lines = [f"## {title}", ""]
    if not stacks:
        lines.append("- None.")
        lines.append("")
        return lines
    for stack in stacks:
        recommendation = (
            f"; recommendation: {stack.recommendation}" if stack.recommendation else ""
        )
        lines.append(f"- {stack.id} (confidence: {stack.confidence:.2f}{recommendation})")
    lines.append("")
    return lines


def _append_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
