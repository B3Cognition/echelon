"""Provider-free structural certification of governance artifacts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from harness.lexicon_gate_io import write_json_atomic as _write_json_atomic


StructuralAction = Literal["proceed", "repair", "proceed_with_warning", "block"]

_ARTIFACTS = {
    "feasibility": ("feasibility.md", "feasibility_structural"),
    "intent-alignment-check": (
        "intent-alignment-check.md",
        "intent_alignment_check_structural",
    ),
}


@dataclass(frozen=True)
class GovernanceStructuralGateResult:
    """Complete deterministic outcome for one governance structural gate."""

    artifact_key: str
    action: StructuralAction
    passed: bool
    attempts: int
    findings: int
    report_path: Path | None
    exhausted_artifact: str | None
    blocked_reason: str | None
    detail: str

    def state_updates(self) -> dict[str, object]:
        try:
            prefix = _ARTIFACTS[self.artifact_key][1]
        except KeyError as exc:
            raise ValueError(
                f"unsupported governance structural artifact: {self.artifact_key!r}"
            ) from exc
        updates: dict[str, object] = {
            "structural_action": self.action,
            f"{prefix}_pass": self.passed,
            f"{prefix}_attempts": self.attempts,
            f"{prefix}_findings": self.findings,
        }
        if self.report_path is not None:
            updates[f"{prefix}_report"] = str(self.report_path)
        if self.exhausted_artifact is not None:
            updates["governance_gate_exhausted"] = self.exhausted_artifact
        return updates


def run_governance_structural_gate(
    *,
    artifact_key: str,
    spec_dir: Path | None,
    extension_root: Path,
    governance_config: Mapping[str, object],
    previous_attempts: object,
    iteration: object,
    max_iterations: object,
) -> GovernanceStructuralGateResult:
    """Validate one configured artifact and return state without mutating it."""
    attempts = _nonnegative_int(previous_attempts)
    if artifact_key not in _ARTIFACTS:
        return _blocked(
            artifact_key,
            attempts,
            "governance_structural_artifact_unknown",
            f"unknown governance structural artifact: {artifact_key}",
        )

    try:
        governance, entry = _resolve_config(governance_config, artifact_key)
    except ValueError as exc:
        return _blocked(
            artifact_key,
            attempts,
            "governance_structural_config_invalid",
            str(exc),
        )

    if (
        not governance.get("enabled", False)
        or entry is None
        or entry.get("enabled", True) is False
        or str(entry.get("tier") or "").lower() != "structural"
    ):
        return GovernanceStructuralGateResult(
            artifact_key=artifact_key,
            action="proceed",
            passed=True,
            attempts=0,
            findings=0,
            report_path=None,
            exhausted_artifact=None,
            blocked_reason=None,
            detail="governance structural gate bypassed",
        )

    if spec_dir is None:
        return _blocked(
            artifact_key,
            attempts,
            "governance_structural_spec_dir_invalid",
            "spec_dir is missing",
        )
    spec_dir = Path(spec_dir).resolve()
    if not spec_dir.is_dir():
        return _blocked(
            artifact_key,
            attempts,
            "governance_structural_spec_dir_invalid",
            f"spec_dir is not a directory: {spec_dir}",
        )

    try:
        artifact_path = _confined_path(
            spec_dir, entry.get("path"), _ARTIFACTS[artifact_key][0]
        )
        report_path = _confined_path(
            spec_dir,
            entry.get("report"),
            f"{artifact_key}-structural-report.json",
        )
        report = _validate(
            artifact_key=artifact_key,
            artifact_path=artifact_path,
            spec_dir=spec_dir,
            extension_root=extension_root.resolve(),
            entry=entry,
        )
    except ValueError as exc:
        return _blocked(
            artifact_key,
            attempts,
            "governance_structural_config_invalid",
            str(exc),
        )

    result = _report_result(artifact_key, report_path, report, governance,
                            attempts, iteration, max_iterations)
    try:
        _write_json_atomic(report_path, report)
    except Exception as exc:
        return GovernanceStructuralGateResult(
            artifact_key=artifact_key,
            action="block",
            passed=False,
            attempts=attempts,
            findings=len(report["findings"]),
            report_path=None,
            exhausted_artifact=result.exhausted_artifact,
            blocked_reason="governance_structural_evidence_write_failed",
            detail=f"could not persist governance structural report: {exc}",
        )

    return result


def _report_result(artifact_key, report_path, report, governance, attempts,
                   iteration, max_iterations):
    """One native policy for captured and file-backed validation outcomes."""
    validation_attempts = 0 if report["ok"] else attempts + 1
    exhausted = False
    if not report["ok"]:
        repair_cap = _nonnegative_int(governance.get("max_repair_attempts", 3))
        iteration_value = _nonnegative_int(iteration)
        iteration_cap = _nonnegative_int(max_iterations)
        exhausted = (
            (repair_cap > 0 and validation_attempts >= repair_cap)
            or (iteration_cap > 0 and iteration_value >= iteration_cap)
        )
    findings = len(report["findings"])
    if report["ok"]:
        action: StructuralAction = "proceed"
        blocked_reason = None
        exhausted_artifact = None
    elif not exhausted:
        action = "repair"
        blocked_reason = None
        exhausted_artifact = None
    elif str(governance.get("on_exhausted") or "warn").lower() == "block":
        action = "block"
        blocked_reason = "governance_structural_exhausted"
        exhausted_artifact = artifact_key
    else:
        action = "proceed_with_warning"
        blocked_reason = None
        exhausted_artifact = artifact_key

    return GovernanceStructuralGateResult(
        artifact_key=artifact_key,
        action=action,
        passed=bool(report["ok"]),
        attempts=validation_attempts,
        findings=findings,
        report_path=report_path,
        exhausted_artifact=exhausted_artifact,
        blocked_reason=blocked_reason,
        detail=f"{findings} finding(s)",
    )


def evaluate_captured_governance_structural_gate(
    *, artifact_key: str, spec_dir: Path, governance_config: Mapping[str, object],
    artifact_text: str | None, reference_texts: Mapping[str, str | None],
    template_text: str | None, previous_attempts: object, iteration: object,
    max_iterations: object,
) -> tuple[GovernanceStructuralGateResult, dict[str, object] | None]:
    """Evaluate caller-authenticated captures; grant no read or publication authority.

    Paths are lexical names of the captured inputs, never resolved against the
    live filesystem. The capture owner must authenticate the actual descriptors.
    Missing mapping keys are uncaptured inputs; None means captured absence.
    Only bundled validator resources may be loaded; live artifact, reference,
    template reads and report writes are outside this evaluation boundary.
    """
    attempts = _nonnegative_int(previous_attempts)
    if artifact_key not in _ARTIFACTS:
        return _blocked(artifact_key, attempts, "governance_structural_artifact_unknown",
                        f"unknown governance structural artifact: {artifact_key}"), None
    try:
        governance, entry = _resolve_config(governance_config, artifact_key)
    except ValueError as exc:
        return _blocked(artifact_key, attempts, "governance_structural_config_invalid", str(exc)), None
    if (not governance.get("enabled", False) or entry is None
            or entry.get("enabled", True) is False
            or str(entry.get("tier") or "").lower() != "structural"):
        return GovernanceStructuralGateResult(artifact_key, "proceed", True, 0, 0,
            None, None, None, "governance structural gate bypassed"), None
    try:
        root = Path(spec_dir)
        if not root.is_absolute() or ".." in root.parts:
            raise ValueError("captured specification root must be absolute")
        def selected_path(configured, default):
            candidate = root / str(configured or default).strip()
            if candidate == root or ".." in candidate.parts or not candidate.is_relative_to(root):
                raise ValueError("captured governance path escapes its specification")
            return candidate
        artifact_path = selected_path(entry.get("path"), _ARTIFACTS[artifact_key][0])
        report_path = selected_path(entry.get("report"), f"{artifact_key}-structural-report.json")
        if artifact_text is not None and type(artifact_text) is not str:
            raise ValueError("captured artifact must be text or explicit absence")
        if entry.get("template"):
            template = Path(str(entry["template"]).strip())
            if template.is_absolute() or ".." in template.parts or template == Path("."):
                raise ValueError("captured template selection must stay within templates")
            if type(template_text) is not str:
                raise ValueError("configured structural template was not captured")
        if not isinstance(reference_texts, Mapping):
            raise ValueError("captured references must be a mapping")
        references = []
        for ref in entry.get("cross_refs") or []:
            if not isinstance(ref, Mapping):
                raise ValueError("governance cross-reference must be an object")
            against = str(ref.get("against") or "").strip()
            if not against:
                continue
            selected_path(against, against)
            if against not in reference_texts or (reference_texts[against] is not None
                    and type(reference_texts[against]) is not str):
                raise ValueError("configured reference was not captured")
            references.append((against, reference_texts[against]))
    except (TypeError, ValueError) as exc:
        return _blocked(artifact_key, attempts, "governance_structural_capture_invalid", str(exc)), None

    findings = []
    if artifact_text is None:
        findings.append(dict(code="missing-structural-artifact",
            message=f"required governance artifact is missing: {artifact_path.name}", artifact=artifact_path.name))
    else:
        chunks = []
        for against, text in references:
            if text is None:
                findings.append(dict(code="missing-cross-reference",
                    message=f"structural reference artifact is missing: {against}", artifact=against))
            else:
                chunks.append(text)
        try:
            from lexicon.structural import structural_validate
            validation = structural_validate(artifact_text, dict(entry),
                spec_text="\n\n".join(chunks), template_text=template_text)
            findings.extend(dict(code=str(item.code), message=str(item.message),
                line=int(item.line), span=str(item.span)) for item in validation.findings)
        except Exception as exc:
            findings.append(dict(code="structural-validator-error", message=f"structural validator failed: {exc}"))
    report = dict(schema_version=1, artifact=artifact_key, path=str(artifact_path),
                  ok=not findings, findings=findings)
    return _report_result(artifact_key, report_path, report, governance,
                          attempts, iteration, max_iterations), report


def _resolve_config(
    config: Mapping[str, object], artifact_key: str
) -> tuple[Mapping[str, object], Mapping[str, object] | None]:
    governance = config.get("governance")
    if not isinstance(governance, Mapping):
        raise ValueError("governance configuration must be an object")
    artifacts = governance.get("artifacts")
    if artifacts is None:
        return governance, None
    if not isinstance(artifacts, Mapping):
        raise ValueError("governance.artifacts must be an object")
    entry = artifacts.get(artifact_key)
    if entry is None:
        return governance, None
    if not isinstance(entry, Mapping):
        raise ValueError(f"governance artifact {artifact_key!r} must be an object")
    cross_refs = entry.get("cross_refs", [])
    if cross_refs is not None and not isinstance(cross_refs, list):
        raise ValueError(f"governance artifact {artifact_key!r} cross_refs must be a list")
    return governance, entry


def _confined_path(root: Path, configured: object, default: str) -> Path:
    name = str(configured or default).strip()
    if not name:
        raise ValueError(f"configured governance path is empty: {default}")
    candidate = (root / name).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"configured governance path escapes its root: {name}") from exc
    return candidate


def _validate(
    *,
    artifact_key: str,
    artifact_path: Path,
    spec_dir: Path,
    extension_root: Path,
    entry: Mapping[str, object],
) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    if not artifact_path.is_file():
        findings.append(
            {
                "code": "missing-structural-artifact",
                "message": (
                    f"required governance artifact is missing: {artifact_path.name}"
                ),
                "artifact": artifact_path.name,
            }
        )
    else:
        spec_chunks: list[str] = []
        for cross_ref in entry.get("cross_refs") or []:
            if not isinstance(cross_ref, Mapping):
                raise ValueError("governance cross-reference must be an object")
            against = str(cross_ref.get("against") or "").strip()
            if not against:
                continue
            spec_path = _confined_path(spec_dir, against, against)
            if spec_path.is_file():
                spec_chunks.append(
                    spec_path.read_text(encoding="utf-8", errors="replace")
                )
            else:
                findings.append(
                    {
                        "code": "missing-cross-reference",
                        "message": (
                            f"structural reference artifact is missing: {against}"
                        ),
                        "artifact": against,
                    }
                )
        try:
            from lexicon.structural import structural_validate

            validation_entry = dict(entry)
            template = str(validation_entry.get("template") or "").strip()
            if template:
                validation_entry["template"] = _confined_path(
                    extension_root / "templates", template, template
                )
            validation = structural_validate(
                artifact_path.read_text(encoding="utf-8", errors="replace"),
                validation_entry,
                spec_text="\n\n".join(spec_chunks),
            )
            findings.extend(
                {
                    "code": str(item.code),
                    "message": str(item.message),
                    "line": int(item.line),
                    "span": str(item.span),
                }
                for item in validation.findings
            )
        except Exception as exc:
            findings.append(
                {
                    "code": "structural-validator-error",
                    "message": f"structural validator failed: {exc}",
                }
            )
    return {
        "schema_version": 1,
        "artifact": artifact_key,
        "path": str(artifact_path),
        "ok": not findings,
        "findings": findings,
    }


def _blocked(
    artifact_key: str, attempts: int, reason: str, detail: str
) -> GovernanceStructuralGateResult:
    return GovernanceStructuralGateResult(
        artifact_key=artifact_key,
        action="block",
        passed=False,
        attempts=attempts,
        findings=0,
        report_path=None,
        exhausted_artifact=None,
        blocked_reason=reason,
        detail=detail,
    )


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
