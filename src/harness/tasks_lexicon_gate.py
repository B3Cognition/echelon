"""Provider-free certification of the configured tasks Lexicon artifact."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from harness.lexicon_gate_io import write_json_atomic


TASKS_LEXICON_ACTIONS = frozenset(
    {"proceed", "repair", "proceed_with_warning", "block"}
)

_REQUIRED_PLAN_OUTPUTS = (
    "critical-path.md",
    "risk-matrix.md",
    "dependencies.md",
)


@dataclass(frozen=True)
class TasksLexiconGateResult:
    """Complete deterministic outcome for one tasks Lexicon node execution."""

    action: str
    passed: bool
    attempts: int
    findings: int
    report_path: Path | None = None
    blocked_reason: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.action not in TASKS_LEXICON_ACTIONS:
            raise ValueError(f"unsupported tasks Lexicon action: {self.action!r}")

    def state_updates(self) -> dict[str, object]:
        updates: dict[str, object] = {
            "tasks_lexicon_action": self.action,
            "tasks_lexicon_pass": self.passed,
            "tasks_lexicon_attempts": self.attempts,
            "tasks_lexicon_findings": self.findings,
        }
        if self.report_path is not None:
            updates["tasks_lexicon_report"] = str(self.report_path)
        if self.blocked_reason:
            updates["blocked_reason"] = self.blocked_reason
        return updates


def run_tasks_lexicon_gate(
    *,
    project_root: Path,
    spec_dir_ref: str,
    config: Mapping[str, object],
    previous_attempts: object,
    workflow_iteration: object,
    max_workflow_iterations: object,
) -> TasksLexiconGateResult:
    """Validate configured planning artifacts without invoking a provider."""
    gate = config.get("lexicon_gate")
    gate = gate if isinstance(gate, dict) else {}
    artifacts = gate.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    tasks_gate = artifacts.get("tasks")
    tasks_gate = tasks_gate if isinstance(tasks_gate, dict) else {}

    if not gate.get("enabled", False) or not tasks_gate.get("enabled", False):
        return TasksLexiconGateResult(
            action="proceed",
            passed=True,
            attempts=0,
            findings=0,
            detail="tasks Lexicon gate disabled",
        )

    prior_attempts = _nonnegative_int(previous_attempts)
    spec_dir_text = str(spec_dir_ref or "").strip()
    if not spec_dir_text:
        return _blocked(
            attempts=prior_attempts,
            reason="tasks_lexicon_spec_dir_missing",
            detail="spec_dir is missing",
        )
    spec_dir = Path(spec_dir_text)
    if not spec_dir.is_absolute():
        spec_dir = project_root / spec_dir
    spec_dir = spec_dir.resolve()
    if not spec_dir.is_dir():
        return _blocked(
            attempts=prior_attempts,
            reason="tasks_lexicon_spec_dir_missing",
            detail=f"spec_dir is not a directory: {spec_dir}",
        )

    try:
        tasks_name, tasks_path = _configured_path(
            spec_dir,
            tasks_gate.get("path"),
            "tasks.md",
        )
        spec_ref_name, spec_ref_path = _configured_path(
            spec_dir,
            tasks_gate.get("spec_ref"),
            "requirements.lexicon.md",
        )
        glossary_name, glossary_path = _configured_path(
            spec_dir,
            tasks_gate.get("glossary_file") or gate.get("glossary_file"),
            "glossary.md",
        )
        _report_name, report_path = _configured_path(
            spec_dir,
            tasks_gate.get("report"),
            "tasks-lexicon-report.json",
        )
    except ValueError as exc:
        return _blocked(
            attempts=prior_attempts,
            reason="tasks_lexicon_config_invalid",
            detail=str(exc),
        )

    report = _validate_tasks_gate_artifacts(
        spec_dir=spec_dir,
        tasks_name=tasks_name,
        tasks_path=tasks_path,
        spec_ref_name=spec_ref_name,
        spec_ref_path=spec_ref_path,
        glossary_path=glossary_path,
    )
    try:
        write_json_atomic(report_path, report)
    except Exception as exc:
        return _blocked(
            attempts=prior_attempts,
            reason="tasks_lexicon_evidence_write_failed",
            detail=f"could not persist tasks Lexicon report: {exc}",
        )

    if report["ok"]:
        return TasksLexiconGateResult(
            action="proceed",
            passed=True,
            attempts=0,
            findings=0,
            report_path=report_path,
            detail="0 finding(s)",
        )

    attempts = prior_attempts + 1
    repair_cap = _nonnegative_int(gate.get("max_repair_attempts", 3))
    iteration = _nonnegative_int(workflow_iteration)
    iteration_cap = _nonnegative_int(max_workflow_iterations)
    exhausted = (
        (repair_cap > 0 and attempts >= repair_cap)
        or (iteration_cap > 0 and iteration >= iteration_cap)
    )
    if not exhausted:
        action = "repair"
        blocked_reason = None
    elif str(gate.get("on_exhausted", "block")).lower() == "warn":
        action = "proceed_with_warning"
        blocked_reason = None
    else:
        action = "block"
        blocked_reason = "lexicon_gate_exhausted"
    findings = len(report["findings"])
    return TasksLexiconGateResult(
        action=action,
        passed=False,
        attempts=attempts,
        findings=findings,
        report_path=report_path,
        blocked_reason=blocked_reason,
        detail=f"{findings} finding(s)",
    )


def _blocked(
    *,
    attempts: int,
    reason: str,
    detail: str,
) -> TasksLexiconGateResult:
    return TasksLexiconGateResult(
        action="block",
        passed=False,
        attempts=attempts,
        findings=0,
        blocked_reason=reason,
        detail=detail,
    )


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _configured_path(
    spec_dir: Path,
    configured: object,
    default: str,
) -> tuple[str, Path]:
    name = str(configured or default).strip()
    if not name:
        raise ValueError(f"configured Lexicon artifact path is empty: {default}")
    candidate = (spec_dir / name).resolve()
    try:
        candidate.relative_to(spec_dir)
    except ValueError as exc:
        raise ValueError(
            f"configured Lexicon artifact path escapes spec_dir: {name}"
        ) from exc
    return name, candidate


def _validate_tasks_gate_artifacts(
    *,
    spec_dir: Path,
    tasks_name: str,
    tasks_path: Path,
    spec_ref_name: str,
    spec_ref_path: Path,
    glossary_path: Path,
) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    for artifact in (tasks_name, *_REQUIRED_PLAN_OUTPUTS):
        if not (spec_dir / artifact).is_file():
            findings.append(
                {
                    "code": "missing-plan-output",
                    "message": f"required planning artifact is missing: {artifact}",
                    "artifact": artifact,
                }
            )
    if not spec_ref_path.is_file():
        findings.append(
            {
                "code": "missing-spec-ref",
                "message": (
                    f"tasks specification reference is missing: {spec_ref_name}"
                ),
                "artifact": spec_ref_name,
            }
        )

    if tasks_path.is_file() and spec_ref_path.is_file():
        tasks_text = tasks_path.read_text(encoding="utf-8")
        try:
            from lexicon.tasks import validate_tasks

            lexicon_report = validate_tasks(
                tasks_text,
                glossary=_load_glossary_terms(glossary_path),
                spec_text=spec_ref_path.read_text(encoding="utf-8"),
            )
            findings.extend(
                {
                    "code": str(item.code),
                    "message": str(item.message),
                    "line": int(item.line),
                    "span": str(item.span),
                }
                for item in lexicon_report.findings
            )
        except Exception as exc:
            findings.append(
                {
                    "code": "tasks-validator-error",
                    "message": f"tasks validator failed: {exc}",
                }
            )

        try:
            from harness.spec_frontmatter import read_targets
            from harness.task_targets import validate_task_targets

            target_report = validate_task_targets(
                tasks_text,
                declared_targets=read_targets(spec_dir),
                allow_legacy_single_target=False,
            )
            target_findings = (
                ("undeclared-target", target_report.missing_targets),
                ("unused-declared-target", target_report.unreferenced_targets),
                ("task-without-target", target_report.unowned_tasks),
                (
                    "cross-target-task",
                    tuple(sorted(target_report.cross_target_tasks)),
                ),
                (
                    "target-file-mismatch",
                    tuple(sorted(target_report.path_target_mismatches)),
                ),
            )
            for code, values in target_findings:
                for value in values:
                    findings.append(
                        {
                            "code": code,
                            "message": f"task target ownership failure: {value}",
                            "target": str(value),
                        }
                    )
        except Exception as exc:
            findings.append(
                {
                    "code": "task-target-validator-error",
                    "message": f"task target validator failed: {exc}",
                }
            )

    return {
        "schema_version": 1,
        "ok": not findings,
        "tasks": tasks_name,
        "spec_ref": spec_ref_name,
        "findings": findings,
    }


def _load_glossary_terms(glossary_path: Path) -> set[str]:
    if not glossary_path.is_file():
        return set()
    glossary: set[str] = set()
    for raw in glossary_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        terms = re.findall(r"\*\*([^*]+)\*\*", line)
        glossary.update(term.strip() for term in terms or [line])
    return glossary
