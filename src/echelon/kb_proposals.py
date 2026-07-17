"""Phase A knowledge-base proposal validation and application."""

from __future__ import annotations

import hashlib
import re
import subprocess
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

LIST_TARGET_ENTRY_KEYS = {
    "knowledge-base/sage-decisions.yaml": "entries",
    "knowledge-base/patterns.yaml": "entries",
    "knowledge-base/pitfalls.yaml": "entries",
}
LIST_TARGET_SCHEMA_FIELDS = {
    "knowledge-base/sage-decisions.yaml": {"schema_version": 2, "append_only": True},
    "knowledge-base/patterns.yaml": {"schema_version": 1},
    "knowledge-base/pitfalls.yaml": {"schema_version": 1},
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


@dataclass(frozen=True)
class ProposalApplyOutcome:
    proposal_id: str
    operation_id: str | None
    proposal_type: str | None
    outcome: str
    targets: list[str]
    reason: str | None = None


@dataclass(frozen=True)
class KBApplyReport:
    run_id: str
    status: str
    outcomes: list[ProposalApplyOutcome]
    report_path: Path
    report_error: str | None = None

    @property
    def accepted_count(self) -> int:
        return sum(1 for item in self.outcomes if item.outcome == "accepted")

    @property
    def rejected_count(self) -> int:
        return sum(1 for item in self.outcomes if item.outcome == "rejected")

    @property
    def skipped_duplicate_count(self) -> int:
        return sum(1 for item in self.outcomes if item.outcome == "skipped_duplicate")

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": 1,
            "run_id": self.run_id,
            "status": self.status,
            "proposal_count": len(self.outcomes),
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "skipped_duplicate_count": self.skipped_duplicate_count,
            "outcomes": [item.__dict__ for item in self.outcomes],
        }
        if self.report_error is not None:
            result["report_error"] = self.report_error
        return result


def apply_proposals(project_root: Path, run_id: str) -> KBApplyReport:
    proposal_dir = project_root / "runs" / run_id / "kb-proposals"
    report_path = project_root / "runs" / run_id / "kb-apply-report.yaml"
    report_error: str | None = None
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        report_error = f"report directory creation failed: {exc}"
    outcomes: list[ProposalApplyOutcome] = []

    try:
        import yaml
    except Exception as exc:
        report_error = _combine_report_errors(report_error, f"PyYAML unavailable: {exc}")
        return _finalize_apply_report(
            run_id,
            report_path,
            outcomes,
            "degraded",
            None,
            report_error,
        )

    try:
        loaded_proposals = load_proposals(proposal_dir, expected_run_id=run_id)
    except Exception as exc:
        outcomes.append(
            ProposalApplyOutcome(
                proposal_id="__system__",
                operation_id=None,
                proposal_type=None,
                outcome="rejected",
                targets=[],
                reason=f"proposal loading failed: {exc}",
            )
        )
        return _finalize_apply_report(
            run_id,
            report_path,
            outcomes,
            "degraded",
            yaml,
            report_error,
        )

    for loaded in loaded_proposals:
        data = loaded.data or {}
        proposal_id = str(data.get("proposal_id") or loaded.path.name)
        proposal_type = data.get("proposal_type") if isinstance(data.get("proposal_type"), str) else None
        targets = data.get("targets") if isinstance(data.get("targets"), list) else []
        target_names = [str(target) for target in targets]
        if not loaded.validation.ok:
            outcomes.append(
                ProposalApplyOutcome(
                    proposal_id=proposal_id,
                    operation_id=loaded.validation.operation_id,
                    proposal_type=proposal_type,
                    outcome="rejected",
                    targets=target_names,
                    reason="; ".join(f"{i.path}: {i.message}" for i in loaded.validation.issues),
                )
            )
            continue
        if proposal_type in {"calibration_observation", "internalization_observation"}:
            outcomes.append(
                ProposalApplyOutcome(
                    proposal_id=proposal_id,
                    operation_id=loaded.validation.operation_id,
                    proposal_type=proposal_type,
                    outcome="needs_review",
                    targets=target_names,
                    reason="aggregate target applier not implemented in first slice",
                )
            )
            continue
        try:
            outcome = _apply_list_proposal(project_root, data, loaded.validation.operation_id)
        except Exception as exc:
            outcome = ProposalApplyOutcome(
                proposal_id=proposal_id,
                operation_id=loaded.validation.operation_id,
                proposal_type=proposal_type,
                outcome="rejected",
                targets=target_names,
                reason=f"apply failed: {exc}",
            )
        outcomes.append(outcome)

    status = "applied" if any(item.outcome == "accepted" for item in outcomes) else "degraded"
    return _finalize_apply_report(
        run_id=run_id,
        report_path=report_path,
        outcomes=outcomes,
        status=status,
        yaml_module=yaml,
        report_error=report_error,
    )


def publish_kb_reports(project_root: Path, run_id: str, spec_dir: Path) -> Path | None:
    run_dir = project_root / "runs" / run_id
    apply_report = run_dir / "kb-apply-report.yaml"
    usage = run_dir / "kb-usage.yaml"
    if not apply_report.exists() and not usage.exists():
        return None

    out_dir = spec_dir / "kb"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        if apply_report.exists():
            (out_dir / "kb-apply-report.yaml").write_text(
                apply_report.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        if usage.exists():
            (out_dir / "kb-usage-summary.yaml").write_text(
                usage.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
    except OSError:
        return None
    return out_dir


def _finalize_apply_report(
    run_id: str,
    report_path: Path,
    outcomes: list[ProposalApplyOutcome],
    status: str,
    yaml_module: Any | None,
    report_error: str | None,
) -> KBApplyReport:
    report = KBApplyReport(
        run_id=run_id,
        status="degraded" if report_error else status,
        outcomes=outcomes,
        report_path=report_path,
        report_error=report_error,
    )
    if report_error is None and yaml_module is not None:
        try:
            report_path.write_text(
                yaml_module.safe_dump(report.to_dict(), sort_keys=False),
                encoding="utf-8",
            )
        except Exception as exc:
            report_error = f"report write failed: {exc}"
            report = KBApplyReport(
                run_id=run_id,
                status="degraded",
                outcomes=outcomes,
                report_path=report_path,
                report_error=report_error,
            )
    return report


def _combine_report_errors(existing: str | None, new: str) -> str:
    return f"{existing}; {new}" if existing else new


def _apply_list_proposal(
    project_root: Path,
    data: dict[str, Any],
    operation_id: str | None,
) -> ProposalApplyOutcome:
    import yaml

    targets = [str(target) for target in data.get("targets", [])]
    target = targets[0]
    target_path = project_root / target
    proposal_id = str(data["proposal_id"])
    proposal_type = str(data["proposal_type"])
    if not target_path.exists():
        return ProposalApplyOutcome(proposal_id, operation_id, proposal_type, "rejected", targets, "target file missing")

    try:
        document = yaml.safe_load(target_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return ProposalApplyOutcome(
            proposal_id,
            operation_id,
            proposal_type,
            "rejected",
            targets,
            f"cannot parse target YAML: {exc}",
        )
    if not isinstance(document, dict):
        return ProposalApplyOutcome(proposal_id, operation_id, proposal_type, "rejected", targets, "target document must be a mapping")

    from codegen.memory.kb_schema_validator import validate_kb_document

    entries_key = LIST_TARGET_ENTRY_KEYS[target]
    baseline_validation = validate_kb_document(target_path.name, document)
    legacy_reason = None
    if not baseline_validation.ok:
        legacy_reason = "; ".join(
            f"{issue.path}: {issue.message}" for issue in baseline_validation.issues
        )
    entries = document.get(entries_key)
    if not isinstance(entries, list):
        return ProposalApplyOutcome(proposal_id, operation_id, proposal_type, "rejected", targets, "target entries must be a list")
    if any(isinstance(entry, dict) and entry.get("operation_id") == operation_id for entry in entries):
        return ProposalApplyOutcome(proposal_id, operation_id, proposal_type, "skipped_duplicate", targets)

    entry = _canonical_entry(data, operation_id, project_root)
    entries.append(entry)
    candidate_document = dict(LIST_TARGET_SCHEMA_FIELDS[target])
    candidate_document[entries_key] = [entry]
    result_validation = validate_kb_document(target_path.name, candidate_document)
    if not result_validation.ok:
        reason = "; ".join(
            f"{issue.path}: {issue.message}" for issue in result_validation.issues
        )
        return ProposalApplyOutcome(
            proposal_id,
            operation_id,
            proposal_type,
            "rejected",
            targets,
            f"resulting target schema invalid: {reason}",
        )
    try:
        target_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    except Exception as exc:
        return ProposalApplyOutcome(
            proposal_id,
            operation_id,
            proposal_type,
            "rejected",
            targets,
            f"target write failed: {exc}",
        )
    reason = f"existing target schema debt: {legacy_reason}" if legacy_reason else None
    return ProposalApplyOutcome(proposal_id, operation_id, proposal_type, "accepted", targets, reason)


def _canonical_entry(
    data: dict[str, Any],
    operation_id: str | None,
    project_root: Path,
) -> dict[str, Any]:
    payload = dict(data["payload"])
    if payload.get("project_fingerprint") == "auto":
        payload["project_fingerprint"] = _project_fingerprint(project_root)
    entry: dict[str, Any] = {
        "operation_id": operation_id,
        "run_id": data["run_id"],
        "source": data["agent"],
        "created_at": data["created_at"],
    }
    if "confidence" in data:
        entry["confidence"] = data["confidence"]
    entry.update(payload)
    return entry


def _project_fingerprint(project_root: Path) -> str:
    identity = ""
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "remote", "get-url", "origin"],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode == 0:
            identity = result.stdout.strip()
    except Exception:
        pass
    if not identity:
        identity = str(project_root.resolve())
    raw = identity.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


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
