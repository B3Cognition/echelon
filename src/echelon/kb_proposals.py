"""Phase A knowledge-base proposal validation and application."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

PROPOSAL_TARGETS: dict[str, set[str]] = {
    "sage_decision": {"knowledge-base/sage-decisions.yaml"},
    "pattern": {"knowledge-base/patterns.yaml"},
    "pitfall": {"knowledge-base/pitfalls.yaml"},
    "calibration_observation": {
        "knowledge-base/calibration-profile.yaml",
        "knowledge-base/estimates-log.yaml",
    },
    "internalization_observation": {
        "knowledge-base/internalization-log.yaml",
        "knowledge-base/agent-scores.yaml",
        "knowledge-base/evolution-signals.yaml",
    },
}


@dataclass(frozen=True)
class ProposalValidationIssue:
    path: str
    message: str


@dataclass(frozen=True)
class ProposalValidationResult:
    ok: bool
    issues: list[ProposalValidationIssue] = field(default_factory=list)
    operation_id: str | None = None


@dataclass(frozen=True)
class LoadedProposal:
    path: Path
    data: dict[str, Any] | None
    validation: ProposalValidationResult


def validate_proposal_document(
    filename: str,
    data: Any,
    *,
    expected_run_id: str | None = None,
) -> ProposalValidationResult:
    issues: list[ProposalValidationIssue] = []
    if not isinstance(data, dict):
        return _result([_issue("$", "proposal must be a mapping")])

    _require(data, "schema_version", issues)
    _require(data, "proposal_id", issues)
    _require(data, "proposal_type", issues)
    _require(data, "run_id", issues)
    _require(data, "agent", issues)
    _require(data, "created_at", issues)
    _require(data, "targets", issues)
    _require(data, "source_artifacts", issues)
    _require(data, "evidence_refs", issues)
    _require(data, "payload", issues)

    if data.get("schema_version") != 1:
        issues.append(_issue("schema_version", "expected 1"))

    proposal_id = data.get("proposal_id")
    if not isinstance(proposal_id, str) or not proposal_id.strip():
        issues.append(_issue("proposal_id", "expected non-empty string"))

    run_id = data.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        issues.append(_issue("run_id", "expected non-empty string"))
    elif expected_run_id is not None and run_id != expected_run_id:
        issues.append(_issue("run_id", f"expected {expected_run_id!r}"))

    operation_id = (
        f"{run_id}/{proposal_id}"
        if isinstance(run_id, str) and isinstance(proposal_id, str)
        else None
    )

    proposal_type = data.get("proposal_type")
    allowed_targets = (
        PROPOSAL_TARGETS.get(proposal_type)
        if isinstance(proposal_type, str)
        else None
    )
    if not isinstance(proposal_type, str) or allowed_targets is None:
        issues.append(_issue("proposal_type", "unsupported proposal type"))

    created_at = data.get("created_at")
    if not _valid_iso_datetime(created_at):
        issues.append(_issue("created_at", "expected ISO-8601 date-time"))

    confidence = data.get("confidence")
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= float(confidence) <= 1
    ):
        issues.append(_issue("confidence", "expected number between 0 and 1"))

    targets = data.get("targets")
    if not isinstance(targets, list) or not targets:
        issues.append(_issue("targets", "expected non-empty list"))
    elif allowed_targets is not None:
        for index, target in enumerate(targets):
            if not isinstance(target, str) or target not in allowed_targets:
                issues.append(_issue(f"targets[{index}]", "target incompatible with proposal_type"))

    for key in ("source_artifacts", "evidence_refs"):
        value = data.get(key)
        if not isinstance(value, list) or not value:
            issues.append(_issue(key, "expected non-empty list"))

    if not isinstance(data.get("payload"), dict):
        issues.append(_issue("payload", "expected mapping"))

    _validate_payload(data, issues)
    return _result(issues, operation_id=operation_id)


def load_proposals(
    proposal_dir: Path,
    *,
    expected_run_id: str | None = None,
) -> list[LoadedProposal]:
    if not proposal_dir.exists():
        return []

    loaded: list[LoadedProposal] = []
    try:
        import yaml
    except Exception as exc:
        for path in sorted(proposal_dir.glob("*.yaml")):
            loaded.append(
                LoadedProposal(
                    path=path,
                    data=None,
                    validation=_result([_issue("$", f"cannot parse YAML: {exc}")]),
                )
            )
        return loaded

    for path in sorted(proposal_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            loaded.append(
                LoadedProposal(
                    path=path,
                    data=None,
                    validation=_result([_issue("$", f"cannot parse YAML: {exc}")]),
                )
            )
            continue
        loaded.append(
            LoadedProposal(
                path=path,
                data=data if isinstance(data, dict) else None,
                validation=validate_proposal_document(
                    path.name,
                    data,
                    expected_run_id=expected_run_id,
                ),
            )
        )
    return loaded


def _validate_payload(data: dict[str, Any], issues: list[ProposalValidationIssue]) -> None:
    proposal_type = data.get("proposal_type")
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return
    required_by_type = {
        "sage_decision": ("artifact", "challenge_type", "challenge_summary", "outcome", "resolution"),
        "pattern": ("name", "domain", "description", "tags", "status", "project_fingerprint", "scope"),
        "pitfall": ("name", "domain", "trigger", "impact", "avoidance", "tags", "status", "project_fingerprint", "scope"),
        "calibration_observation": ("domain", "observation_kind"),
        "internalization_observation": ("subject_agent", "agent_tier", "metrics", "gate_verdict", "computation_health"),
    }
    required_fields = (
        required_by_type.get(proposal_type, ())
        if isinstance(proposal_type, str)
        else ()
    )
    for key in required_fields:
        if key not in payload:
            issues.append(_issue(f"payload.{key}", "required"))


def _valid_iso_datetime(value: Any) -> bool:
    if not isinstance(value, str) or not _ISO_DATETIME_RE.match(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _require(data: dict[str, Any], key: str, issues: list[ProposalValidationIssue]) -> None:
    if key not in data:
        issues.append(_issue(key, "required"))


def _issue(path: str, message: str) -> ProposalValidationIssue:
    return ProposalValidationIssue(path=path, message=message)


def _result(
    issues: list[ProposalValidationIssue],
    *,
    operation_id: str | None = None,
) -> ProposalValidationResult:
    return ProposalValidationResult(ok=not issues, issues=issues, operation_id=operation_id)
