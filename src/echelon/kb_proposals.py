"""Phase A knowledge-base proposal validation and application."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


_ISO_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_LINE_LOCATOR_RE = re.compile(r"^(?:line|L)(?::|-)?(\d+)$", re.IGNORECASE)

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
KNOWN_PROPOSAL_AGENTS = {
    "echelon.adaptive",
    "echelon.advocate",
    "echelon.architect",
    "echelon.auditor",
    "echelon.benchmark",
    "echelon.cartographer",
    "echelon.change-controller",
    "echelon.checkpoint",
    "echelon.chief",
    "echelon.code-reviewer",
    "echelon.commander",
    "echelon.consolidator",
    "echelon.debugger",
    "echelon.docs-verifier",
    "echelon.engineering-manager",
    "echelon.gatekeeper",
    "echelon.golddigger",
    "echelon.guardian",
    "echelon.implementation-mapper",
    "echelon.implementer",
    "echelon.integrator",
    "echelon.internalizer",
    "echelon.investigator",
    "echelon.lexicon-deriver",
    "echelon.maverick",
    "echelon.mirror",
    "echelon.modeler",
    "echelon.monitor",
    "echelon.oracle",
    "echelon.orchestrator",
    "echelon.progress-tracker",
    "echelon.re-analyzer",
    "echelon.re-checklister",
    "echelon.re-constituter",
    "echelon.re-expander",
    "echelon.re-planner",
    "echelon.re-specifier",
    "echelon.re-tasker",
    "echelon.re-validator",
    "echelon.re-verifier",
    "echelon.realist",
    "echelon.sage",
    "echelon.scorekeeper",
    "echelon.scout",
    "echelon.sentinel",
    "echelon.spec-fulfillment-auditor",
    "echelon.spec-guard",
    "echelon.strategist",
    "echelon.synthesizer",
    "echelon.tech-writer",
    "echelon.test-guardian",
    "echelon.tracker",
    "echelon.validator",
    "echelon.verification",
    "echelon.veteran",
    "echelon.visual-validator",
}
RESERVED_PAYLOAD_FIELDS = {"operation_id", "run_id", "source", "created_at", "confidence"}


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

    preflight_report = KBApplyReport(
        run_id=run_id,
        status="degraded",
        outcomes=[],
        report_path=report_path,
    )
    try:
        _persist_apply_report(report_path, preflight_report, yaml)
    except Exception as exc:
        report_error = _combine_report_errors(report_error, f"report write failed: {exc}")
        return KBApplyReport(
            run_id=run_id,
            status="degraded",
            outcomes=[],
            report_path=report_path,
            report_error=report_error,
        )

    try:
        loaded_proposals = load_proposals(
            proposal_dir,
            expected_run_id=run_id,
            project_root=project_root,
        )
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

    mutation_snapshots: dict[Path, str] = {}
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
            outcome = _apply_list_proposal(
                project_root,
                report_path.parent / "kb-mutation-journal.jsonl",
                data,
                loaded.validation.operation_id,
                mutation_snapshots,
            )
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

    unresolved_outcomes = {"rejected", "needs_review"}
    status = (
        "applied"
        if any(item.outcome == "accepted" for item in outcomes)
        and not any(item.outcome in unresolved_outcomes for item in outcomes)
        else "degraded"
    )
    return _finalize_apply_report(
        run_id=run_id,
        report_path=report_path,
        outcomes=outcomes,
        status=status,
        yaml_module=yaml,
        report_error=report_error,
        mutation_snapshots=mutation_snapshots,
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
    except Exception:
        return None
    return out_dir


def accepted_kb_target_paths(project_root: Path, run_id: str) -> tuple[Path, ...]:
    """Return the canonical KB files successfully mutated by this run.

    The persisted apply report is the commit authority.  It proves that the
    deterministic applier completed the mutation; proposal files and the
    pre-write mutation journal do not provide that guarantee.
    """

    root = Path(project_root).resolve()
    report_path = root / "runs" / run_id / "kb-apply-report.yaml"
    if not report_path.exists():
        return ()
    try:
        import yaml

        report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"cannot read KB apply report for run {run_id}: {exc}") from exc
    if not isinstance(report, dict):
        raise ValueError(f"KB apply report for run {run_id} must be a mapping")
    outcomes = report.get("outcomes")
    if not isinstance(outcomes, list):
        # Older/degraded reports did not always persist outcome details.  They
        # cannot prove any canonical mutation, so they authorize no KB paths.
        return ()

    accepted_outcomes = [
        outcome
        for outcome in outcomes
        if isinstance(outcome, dict) and outcome.get("outcome") == "accepted"
    ]
    if not accepted_outcomes:
        return ()
    if str(report.get("run_id") or "") != run_id:
        raise ValueError(f"KB apply report run_id does not match {run_id}")

    known_targets = set().union(*PROPOSAL_TARGETS.values())
    accepted: list[Path] = []
    seen: set[Path] = set()
    for index, outcome in enumerate(outcomes):
        if not isinstance(outcome, dict):
            raise ValueError(f"KB apply report outcome {index} must be a mapping")
        if outcome.get("outcome") != "accepted":
            continue
        targets = outcome.get("targets")
        if not isinstance(targets, list) or not targets:
            raise ValueError(f"accepted KB apply report outcome {index} has no targets")
        for target in targets:
            if not isinstance(target, str) or target not in known_targets:
                raise ValueError(
                    f"accepted KB apply report outcome {index} has an unknown target"
                )
            target_path = (root / target).resolve()
            try:
                target_path.relative_to(root)
            except ValueError as exc:
                raise ValueError(
                    f"accepted KB target must be inside the project root: {target}"
                ) from exc
            if not target_path.is_file():
                raise ValueError(f"accepted KB target is not a file: {target}")
            if target_path not in seen:
                accepted.append(target_path)
                seen.add(target_path)
    return tuple(accepted)


def _finalize_apply_report(
    run_id: str,
    report_path: Path,
    outcomes: list[ProposalApplyOutcome],
    status: str,
    yaml_module: Any | None,
    report_error: str | None,
    mutation_snapshots: dict[Path, str] | None = None,
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
            _persist_apply_report(report_path, report, yaml_module)
        except Exception as exc:
            report_error = f"report write failed: {exc}"
            outcomes = _rollback_accepted_outcomes(outcomes, mutation_snapshots or {}, report_error)
            report = KBApplyReport(
                run_id=run_id,
                status="degraded",
                outcomes=outcomes,
                report_path=report_path,
                report_error=report_error,
            )
    return report


def _persist_apply_report(report_path: Path, report: KBApplyReport, yaml_module: Any) -> None:
    _atomic_replace_text(
        report_path,
        yaml_module.safe_dump(report.to_dict(), sort_keys=False),
    )


def _rollback_accepted_outcomes(
    outcomes: list[ProposalApplyOutcome],
    mutation_snapshots: dict[Path, str],
    report_error: str,
) -> list[ProposalApplyOutcome]:
    rollback_errors: list[str] = []
    for target_path, original_text in mutation_snapshots.items():
        try:
            _atomic_replace_text(target_path, original_text)
        except Exception as exc:
            rollback_errors.append(f"{target_path}: {exc}")
    reason_suffix = report_error
    if rollback_errors:
        reason_suffix = f"{report_error}; rollback failed: {'; '.join(rollback_errors)}"

    rolled_back: list[ProposalApplyOutcome] = []
    for outcome in outcomes:
        if outcome.outcome == "accepted":
            rolled_back.append(
                ProposalApplyOutcome(
                    proposal_id=outcome.proposal_id,
                    operation_id=outcome.operation_id,
                    proposal_type=outcome.proposal_type,
                    outcome="rejected",
                    targets=outcome.targets,
                    reason=f"canonical mutation rolled back because apply report could not be persisted: {reason_suffix}",
                )
            )
        else:
            rolled_back.append(outcome)
    return rolled_back


def _combine_report_errors(existing: str | None, new: str) -> str:
    return f"{existing}; {new}" if existing else new


def _apply_list_proposal(
    project_root: Path,
    mutation_journal_path: Path,
    data: dict[str, Any],
    operation_id: str | None,
    mutation_snapshots: dict[Path, str],
) -> ProposalApplyOutcome:
    import yaml

    targets = [str(target) for target in data.get("targets", [])]
    target = targets[0]
    target_path = project_root / target
    proposal_id = str(data["proposal_id"])
    proposal_type = str(data["proposal_type"])
    try:
        lock_path = _acquire_target_lock(target_path)
    except OSError as exc:
        return ProposalApplyOutcome(
            proposal_id,
            operation_id,
            proposal_type,
            "rejected",
            targets,
            f"target lock unavailable: {exc}",
        )

    try:
        return _apply_locked_list_proposal(
            project_root,
            target_path,
            targets,
            data,
            operation_id,
            yaml,
            mutation_snapshots,
            mutation_journal_path,
        )
    finally:
        _release_target_lock(lock_path)


def _apply_locked_list_proposal(
    project_root: Path,
    target_path: Path,
    targets: list[str],
    data: dict[str, Any],
    operation_id: str | None,
    yaml_module: Any,
    mutation_snapshots: dict[Path, str],
    mutation_journal_path: Path,
) -> ProposalApplyOutcome:
    proposal_id = str(data["proposal_id"])
    proposal_type = str(data["proposal_type"])
    if not target_path.exists():
        return ProposalApplyOutcome(proposal_id, operation_id, proposal_type, "rejected", targets, "target file missing")

    try:
        original_text = target_path.read_text(encoding="utf-8")
        document = yaml_module.safe_load(original_text) or {}
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

    entries_key = LIST_TARGET_ENTRY_KEYS[targets[0]]
    baseline_validation = validate_kb_document(target_path.name, document)
    if not baseline_validation.ok:
        reason = "; ".join(
            f"{issue.path}: {issue.message}" for issue in baseline_validation.issues
        )
        return ProposalApplyOutcome(
            proposal_id,
            operation_id,
            proposal_type,
            "rejected",
            targets,
            f"existing target schema debt: {reason}",
        )
    entries = document.get(entries_key)
    if not isinstance(entries, list):
        return ProposalApplyOutcome(proposal_id, operation_id, proposal_type, "rejected", targets, "target entries must be a list")
    if any(isinstance(entry, dict) and entry.get("operation_id") == operation_id for entry in entries):
        return ProposalApplyOutcome(proposal_id, operation_id, proposal_type, "skipped_duplicate", targets)

    entry = _canonical_entry(data, operation_id, project_root)
    entries.append(entry)
    result_validation = validate_kb_document(target_path.name, document)
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
        mutation_snapshots.setdefault(target_path, original_text)
        _append_mutation_journal(
            mutation_journal_path,
            {
                "operation_id": operation_id,
                "proposal_id": proposal_id,
                "proposal_type": proposal_type,
                "target": targets[0],
                "outcome": "intent_to_write",
            },
        )
        _atomic_replace_text(target_path, yaml_module.safe_dump(document, sort_keys=False))
    except Exception as exc:
        return ProposalApplyOutcome(
            proposal_id,
            operation_id,
            proposal_type,
            "rejected",
            targets,
            f"target write failed: {exc}",
        )
    return ProposalApplyOutcome(proposal_id, operation_id, proposal_type, "accepted", targets)


def _append_mutation_journal(journal_path: Path, entry: dict[str, Any]) -> None:
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _canonical_entry(
    data: dict[str, Any],
    operation_id: str | None,
    project_root: Path,
) -> dict[str, Any]:
    payload = dict(data["payload"])
    if payload.get("project_fingerprint") == "auto":
        payload["project_fingerprint"] = _project_fingerprint(project_root)
    proposal_type = data["proposal_type"]
    if proposal_type in {"pattern", "pitfall"} and not payload.get("id"):
        prefix = "pat" if proposal_type == "pattern" else "pit"
        identity = operation_id or f"{data['run_id']}/{data['proposal_id']}"
        payload["id"] = f"{prefix}-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]}"
    if proposal_type == "sage_decision":
        payload.setdefault("was_correct", True)
    entry: dict[str, Any] = dict(payload)
    entry.update(
        {
            "operation_id": operation_id,
            "run_id": data["run_id"],
            "source": data["agent"],
            "created_at": data["created_at"],
        }
    )
    if "confidence" in data:
        entry["confidence"] = data["confidence"]
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


def _artifact_exists(project_root: Path, artifact: str) -> bool:
    artifact_path = Path(artifact)
    if artifact_path.is_absolute():
        return False
    try:
        candidate = (project_root / artifact_path).resolve()
        root = project_root.resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return False
    return candidate.exists() and candidate.is_file()


def _evidence_locator_exists(project_root: Path, artifact: str, locator: str) -> bool:
    artifact_path = (project_root / Path(artifact)).resolve()
    try:
        text = artifact_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    match = _LINE_LOCATOR_RE.match(locator.strip())
    if match:
        line_number = int(match.group(1))
        return 1 <= line_number <= len(text.splitlines())
    return locator.strip() in text


def validate_proposal_document(
    filename: str,
    data: Any,
    *,
    expected_run_id: str | None = None,
    project_root: Path | None = None,
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

    agent = data.get("agent")
    if not isinstance(agent, str) or agent not in KNOWN_PROPOSAL_AGENTS:
        issues.append(_issue("agent", "expected known Echelon agent identity"))

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

    source_artifacts = data.get("source_artifacts")
    source_artifact_set: set[str] = set()
    if not isinstance(source_artifacts, list) or not source_artifacts:
        issues.append(_issue("source_artifacts", "expected non-empty list"))
    else:
        for index, artifact in enumerate(source_artifacts):
            if not isinstance(artifact, str) or not artifact.strip():
                issues.append(_issue(f"source_artifacts[{index}]", "expected non-empty string"))
                continue
            source_artifact_set.add(artifact)
            if project_root is not None and not _artifact_exists(project_root, artifact):
                issues.append(_issue(f"source_artifacts[{index}]", "artifact must exist under project root"))

    evidence_refs = data.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        issues.append(_issue("evidence_refs", "expected non-empty list"))
    else:
        for index, evidence in enumerate(evidence_refs):
            base = f"evidence_refs[{index}]"
            if not isinstance(evidence, dict):
                issues.append(_issue(base, "expected mapping"))
                continue
            for key in ("artifact", "locator", "claim"):
                if not isinstance(evidence.get(key), str) or not evidence[key].strip():
                    issues.append(_issue(f"{base}.{key}", "expected non-empty string"))
            artifact = evidence.get("artifact")
            if isinstance(artifact, str) and artifact.strip() and artifact not in source_artifact_set:
                issues.append(_issue(f"{base}.artifact", "expected artifact declared in source_artifacts"))
            locator = evidence.get("locator")
            if (
                project_root is not None
                and isinstance(artifact, str)
                and artifact.strip()
                and isinstance(locator, str)
                and locator.strip()
                and _artifact_exists(project_root, artifact)
                and not _evidence_locator_exists(project_root, artifact, locator)
            ):
                issues.append(_issue(f"{base}.locator", "locator must resolve inside artifact"))

    payload = data.get("payload")
    if not isinstance(payload, dict):
        issues.append(_issue("payload", "expected mapping"))
    else:
        for key in sorted(RESERVED_PAYLOAD_FIELDS):
            if key in payload:
                issues.append(_issue(f"payload.{key}", "reserved for deterministic KB applier"))

    _validate_payload(data, issues)
    return _result(issues, operation_id=operation_id)


def load_proposals(
    proposal_dir: Path,
    *,
    expected_run_id: str | None = None,
    project_root: Path | None = None,
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

    seen_proposal_ids: set[str] = set()
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
        validation = validate_proposal_document(
            path.name,
            data,
            expected_run_id=expected_run_id,
            project_root=project_root,
        )
        proposal_id = data.get("proposal_id") if isinstance(data, dict) else None
        if isinstance(proposal_id, str) and proposal_id.strip():
            if proposal_id in seen_proposal_ids:
                validation = _result(
                    [
                        *validation.issues,
                        _issue("proposal_id", f"duplicate proposal_id in run: {proposal_id}"),
                    ],
                    operation_id=validation.operation_id,
                )
            else:
                seen_proposal_ids.add(proposal_id)
        loaded.append(
            LoadedProposal(
                path=path,
                data=data if isinstance(data, dict) else None,
                validation=validation,
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


def _acquire_target_lock(target_path: Path) -> Path:
    lock_path = target_path.with_name(f"{target_path.name}.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    return lock_path


def _release_target_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def _atomic_replace_text(target_path: Path, content: str) -> None:
    fd, temp_name = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=f".{target_path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target_path)
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


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
