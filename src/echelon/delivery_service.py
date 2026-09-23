"""Typed application-service boundary for Delivery commands."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import sys

from harness.gitops import copy_prosaic_runtime_tree, copy_runtime_tree
from harness.phase_a_readiness import validate_phase_a_readiness
from harness.provider_capability import ProviderCapability
from harness.runtime_surface import prune_delivery_workflow_definition
from harness.state import state_lock_owner_is_alive


@dataclass(frozen=True)
class DeliveryRunRequest:
    spec_id: str
    extra_args: tuple[str, ...] = ()
    mode: str | None = None
    max_outer: int | None = None
    max_inner: int | None = None
    token_budget: int | None = None
    auto_merge: bool | None = None
    reset: bool = False


@dataclass(frozen=True)
class DeliveryRecoveryRequest:
    spec_id: str
    extra_args: tuple[str, ...] = ()
    answer: str | None = None
    mode: str | None = None


@dataclass(frozen=True)
class DeliveryLandRequest:
    spec_id: str
    extra_args: tuple[str, ...] = ()
    continue_existing: bool = False
    prepare_only: bool = False
    autoresolve: bool = True
    allow_fulfillment_gaps: bool = False
    strategy: str | None = None


@dataclass(frozen=True)
class LocalVerificationRequest:
    spec_id: str
    target_id: str | None = None
    engine: str = "auto"
    assume_yes: bool = False
    keep_on_failure: bool = False


@dataclass(frozen=True)
class LocalActionPlan:
    """The exact host-local action that an operator confirms before it runs."""

    spec_id: str
    target_id: str
    engine: str
    candidate_fingerprint: str
    planned_actions: tuple[str, ...]
    digest: str
    workspace_root: Path | None = field(default=None, repr=False)
    target_root: Path | None = field(default=None, repr=False)
    candidate: object | None = field(default=None, repr=False)


@dataclass(frozen=True)
class HarnessWorkspaceTarget:
    workspace_root: Path
    workspace_git_role: str
    source_root: Path
    source_id: str
    source_git_role: str


def _delivery_status_escalation(state: dict, project_root: Path) -> dict[str, object] | None:
    """Read optional human-decision details without making status fragile."""
    raw_path = str(state.get("escalation_file") or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = project_root / path
    escalation: dict[str, object] = {"path": str(path)}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return escalation

    def section(name: str) -> str:
        match = re.search(
            rf"^## {re.escape(name)}\s*$\n(.*?)(?=^## |\Z)",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        return match.group(1).strip() if match else ""

    question = section("Question")
    context = section("Context")
    if question:
        escalation["question"] = question
    if context:
        escalation["context"] = context
    metadata = re.search(
        r"^## Decision Metadata\s*$\n```json\s*(\{.*?\})\s*```",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not metadata:
        return escalation
    try:
        decision = json.loads(metadata.group(1))
    except (json.JSONDecodeError, TypeError):
        return escalation
    suggestions = decision.get("suggested_answers") if isinstance(decision, dict) else None
    if not isinstance(suggestions, list):
        return escalation
    choices: list[dict[str, str | bool]] = []
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        answer = str(suggestion.get("answer") or "").strip()
        if not answer:
            continue
        choice = {
            "label": str(suggestion.get("label") or "Suggested answer").strip(),
            "answer": answer,
            "consequence": str(suggestion.get("consequence") or "").strip(),
            "recommended": bool(suggestion.get("recommended")),
        }
        choices.append(choice)
    if choices:
        escalation["choices"] = choices
    return escalation


def _require_delivery_capability(command_name: str, project_root: Path) -> None:
    from echelon.cli import _require_provider_capability

    _require_provider_capability(
        command_name,
        ProviderCapability.BUILD,
        project_dir=project_root,
    )


def _iter_delivery_states(project_root: Path) -> list[dict]:
    from echelon.cli import _iter_harness_build_states

    return _iter_harness_build_states(project_root)


def _outer_cap_delivery_action(
    spec_id: str,
    current_ceiling: object = None,
) -> tuple[str, str]:
    """Return the sole checkpoint-preserving action after outer-loop exhaustion."""
    from harness.convergence import DEFAULT_MAX_OUTER

    try:
        current = max(1, int(current_ceiling or DEFAULT_MAX_OUTER))
    except (TypeError, ValueError):
        current = DEFAULT_MAX_OUTER
    extended = current + DEFAULT_MAX_OUTER
    return (
        f"echelon delivery run {spec_id} --max-outer {extended}",
        "Extends the meaningful-attempt ceiling from the latest durable checkpoint "
        "while preserving the convergence lease.",
    )


def _delivery_status_next_step(
    state: dict,
    spec_id: str,
    escalation: dict[str, object] | None = None,
) -> str:
    status = str(state.get("status") or "unknown")
    termination_reason = str(state.get("termination_reason") or "")
    effective_spec = spec_id or str(state.get("spec_id") or "<spec_id>")
    if status == "converged":
        return f"echelon delivery land {effective_spec}"
    if status == "blocked":
        if termination_reason == "outer_cap":
            command, explanation = _outer_cap_delivery_action(
                effective_spec, state.get("max_outer")
            )
            return f"{command}  # {explanation}"
        if termination_reason == "convergence_stalled":
            return (
                f"echelon delivery continue {effective_spec}  "
                "# one recovery attempt using the recorded high-water evidence"
            )
        if str(state.get("escalation_file") or ""):
            choices = escalation.get("choices") if escalation else None
            if isinstance(choices, list):
                recommended = next(
                    (
                        choice
                        for choice in choices
                        if isinstance(choice, dict) and choice.get("recommended")
                    ),
                    None,
                )
                if isinstance(recommended, dict):
                    answer = str(recommended.get("answer") or "").strip()
                    if answer:
                        return f"echelon delivery resume {effective_spec} {shlex.quote(answer)}"
            return f'echelon delivery resume {effective_spec} "<answer>"'
        if termination_reason == "verify_command_needed":
            return "set delivery.verify_command, then echelon delivery continue " + effective_spec
        if termination_reason == "build_blocked":
            return (
                "resolve the reported blocker, then "
                f"echelon delivery run {effective_spec}"
            )
        return f"echelon delivery continue {effective_spec}"
    if status == "running":
        return (
            "delivery is active; monitor with "
            f"echelon delivery status {effective_spec}"
        )
    if status in {"initialized", "interrupted"}:
        return f"echelon delivery run {effective_spec}"
    if status in {"failed", "cancelled_by_coordinator"}:
        return f"inspect state, then echelon delivery run {effective_spec} --reset if needed"
    return f"echelon delivery run {effective_spec}"


def _delivery_status_effective_state(state: dict) -> dict:
    """Overlay an orphaned running record as an interrupted delivery.

    Status must stay read-only: a later ``delivery run`` owns checkpoint
    recovery.  It still must not tell an operator to wait for a PID that has
    already exited.
    """
    if str(state.get("status") or "") != "running":
        return state
    raw_state_file = str(state.get("state_file") or "").strip()
    if raw_state_file and state_lock_owner_is_alive(Path(raw_state_file)):
        return state
    observed = dict(state)
    observed["status"] = "interrupted"
    observed["termination_reason"] = "execution_lost"
    observed["execution"] = "process exited; checkpoint preserved"
    return observed


def _delivery_status_local_verification(state: Mapping[str, object]) -> dict[str, str] | None:
    """Read immutable local evidence without resolving or modifying a candidate."""
    raw_state_file = str(state.get("state_file") or "").strip()
    if not raw_state_file:
        return None
    state_file = Path(raw_state_file)
    if state_file.is_symlink() or state_file.name == "":
        return None
    build_root = state_file.parent.parent
    evidence_root = build_root / "evidence" / "local-runnability"
    if not evidence_root.exists() or evidence_root.is_symlink():
        return None
    try:
        candidate = _local_evidence_candidate_from_state(state, build_root)
    except ValueError as exc:
        return {
            "status": "unavailable",
            "reason": str(exc),
            "runner": "opt-in macOS (Docker Desktop or Podman)",
        }
    try:
        from harness.local_runner_evidence import select_local_verification_status

        selected = select_local_verification_status(evidence_root, candidate)
    except (OSError, ValueError) as exc:
        return {
            "status": "unavailable",
            "reason": f"local evidence is unreadable: {exc}",
            "runner": "opt-in macOS (Docker Desktop or Podman)",
        }
    result = {
        "status": selected.display_status,
        "runner": "opt-in macOS (Docker Desktop or Podman)",
    }
    if selected.valid_pass_path is not None:
        result["evidence"] = str(selected.valid_pass_path)
    if selected.latest_attempt_path is not None:
        result["last_attempt"] = selected.latest_attempt_status
        result["last_attempt_evidence"] = str(selected.latest_attempt_path)
    return result

def _local_evidence_candidate_from_state(state: Mapping[str, object], build_root: Path):
    """Build the content-authoritative attestation tuple from sealed delivery state."""
    from harness.local_runner_candidate import EffectiveLocalCandidate

    raw_coverage = state.get("coverage_observation")
    snapshot = state.get("delivery_stack_snapshot")
    if not isinstance(raw_coverage, Mapping) or raw_coverage.get("status") != "passed":
        raise ValueError("passing sandbox coverage evidence is unavailable")
    if not isinstance(snapshot, Mapping) or snapshot.get("schema_version") != 1:
        raise ValueError("sealed delivery stack snapshot is unavailable")
    fingerprints = raw_coverage.get("fingerprints")
    reference = raw_coverage.get("ref")
    if not isinstance(fingerprints, Mapping) or not isinstance(reference, Mapping):
        raise ValueError("sandbox evidence fingerprint tuple is unavailable")
    values = {
        "product_fingerprint": fingerprints.get("candidate_fingerprint"),
        "contract_hash": fingerprints.get("runnability_contract_hash"),
        "stack_hash": fingerprints.get("resolved_stack_hash"),
        "observer_plan_hash": fingerprints.get("observer_plan_hash"),
        "sandbox_receipt_sha256": reference.get("receipt_sha256"),
    }
    if not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in values.values()):
        raise ValueError("sandbox evidence fingerprint tuple is malformed")
    if (
        snapshot.get("resolved_stack_hash") != values["stack_hash"]
        or snapshot.get("observer_plan_hash") != values["observer_plan_hash"]
        or not isinstance(snapshot.get("resolved"), Mapping)
    ):
        raise ValueError("sealed stack evidence does not match sandbox coverage")
    build_id = str(state.get("build_id") or build_root.name).strip()
    if not re.fullmatch(r"build-[A-Za-z0-9][A-Za-z0-9._-]{0,127}", build_id):
        raise ValueError("delivery build identity is malformed")
    return EffectiveLocalCandidate(
        build_id=build_id,
        sandbox_candidate_commit="0" * 40,
        effective_candidate_commit="0" * 40,
        product_fingerprint=str(values["product_fingerprint"]),
        contract_hash=str(values["contract_hash"]),
        stack_hash=str(values["stack_hash"]),
        observer_plan_hash=str(values["observer_plan_hash"]),
        sandbox_receipt_sha256=str(values["sandbox_receipt_sha256"]),
        mirror_path=build_root.parent / "mirror.git",
        stack_snapshot=dict(snapshot),
    )

def _delivery_status_summary(
    state: dict,
    *,
    project_root: Path,
) -> dict:
    state = _delivery_status_effective_state(state)
    spec_id = str(state.get("spec_id") or "")
    status = str(state.get("status") or "unknown")
    # Resume deliberately retains terminal fields for recovery/history. They
    # are not facts about a currently active attempt and must not be presented
    # as such by `delivery status`.
    terminal_fields_current = status != "running"
    checkpoints = state.get("checkpoint_commits")
    checkpoint_count = len(checkpoints) if isinstance(checkpoints, list) else 0
    escalation = (
        None
        if str(state.get("termination_reason") or "")
        in {"outer_cap", "convergence_stalled"}
        else _delivery_status_escalation(state, project_root)
    )
    summary = {
        "spec_id": spec_id,
        "build_id": str(state.get("build_id") or ""),
        "status": status,
        "mode": str(state.get("mode") or ""),
        "outer_iter": int(state.get("outer_iter") or 0),
        "inner_iter": int(state.get("inner_iter") or 0),
        "tokens_used": int(state.get("tokens_used") or 0),
        "token_budget": state.get("token_budget"),
        "termination_reason": (
            str(state.get("termination_reason") or "")
            if terminal_fields_current
            else ""
        ),
        "build_status": (
            str(state.get("build_status") or "")
            if terminal_fields_current
            else ""
        ),
        "build_reason": (
            str(state.get("build_reason") or "")
            if terminal_fields_current
            else ""
        ),
        "pr_url": str(state.get("pr_url") or ""),
        "target_branch": str(state.get("target_branch") or ""),
        "target_commit": str(state.get("target_commit") or ""),
        "target": str(
            state.get("target_id")
            or state.get("target_repo")
            or state.get("implementation_target")
            or ""
        ),
        "salvage_branch": str(state.get("salvage_branch") or ""),
        "salvage_commit": str(state.get("salvage_commit") or ""),
        "checkpoint_count": checkpoint_count,
        "state_file": str(state.get("state_file") or ""),
        "execution": str(state.get("execution") or ""),
        "next": _delivery_status_next_step(state, spec_id, escalation),
    }
    convergence = state.get("convergence_lease")
    if isinstance(convergence, dict):
        from harness.convergence import (
            DEFAULT_MAX_OUTER,
            DEFAULT_STALL_PATIENCE,
        )

        summary["convergence"] = {
            "meaningful_attempts": max(
                0, int(convergence.get("meaningful_attempts") or 0)
            ),
            "hard_ceiling": max(
                1, int(state.get("max_outer") or DEFAULT_MAX_OUTER)
            ),
            "stalled_attempts": max(
                0, int(convergence.get("stalled_attempts") or 0)
            ),
            "stall_patience": DEFAULT_STALL_PATIENCE,
            "infrastructure_attempts": max(
                0, int(convergence.get("infrastructure_attempts") or 0)
            ),
            "last_outcome": str(convergence.get("last_outcome") or "not_observed"),
            "last_reason": str(convergence.get("last_reason") or ""),
            "best_checkpoint_commit": str(
                convergence.get("best_checkpoint_commit") or ""
            ),
        }
    if escalation is not None:
        summary["escalation"] = escalation
    publication_failure = state.get("publication_failure")
    if isinstance(publication_failure, dict):
        summary["publication_failure"] = {
            "stage": str(publication_failure.get("stage") or ""),
            "error": str(publication_failure.get("error") or ""),
        }
    runnability = _normalized_delivery_runnability(state.get("user_runnability"))
    if runnability is not None:
        summary["user_runnability"] = runnability
    coverage_observation = _normalized_delivery_coverage_observation(
        state.get("coverage_observation")
    )
    if coverage_observation is not None:
        summary["coverage_observation"] = coverage_observation
    local_verification = _delivery_status_local_verification(state)
    if local_verification is not None:
        summary["local_verification"] = local_verification
    last_verify = state.get("last_verify_result")
    if isinstance(last_verify, dict):
        verification_evidence = last_verify.get("verification_evidence")
        if isinstance(verification_evidence, dict):
            raw_playwright = verification_evidence.get("playwright")
            if isinstance(raw_playwright, dict):
                summary["playwright"] = {
                    key: max(0, int(raw_playwright.get(key) or 0))
                    for key in ("total", "passed", "failed", "skipped")
                }
    visual_evidence = state.get("visual_evidence")
    if isinstance(visual_evidence, dict):
        summary["visual_evidence"] = {
            "path": str(visual_evidence.get("path") or ""),
            "passed": visual_evidence.get("passed") is True,
            "artifact_count": max(0, int(visual_evidence.get("artifact_count") or 0)),
            "candidate_fingerprint": str(
                visual_evidence.get("candidate_fingerprint") or ""
            ),
        }
    try:
        from harness.spec_frontmatter import find_spec_dir, read_frontmatter

        spec_dir = find_spec_dir(spec_id, project_root) if spec_id else None
        if spec_dir is not None:
            summary["spec_dir"] = str(spec_dir)
            frontmatter = read_frontmatter(spec_dir)
            if frontmatter.get("status"):
                summary["spec_status"] = str(frontmatter.get("status"))
                if status == "converged" and summary["spec_status"] == "landed":
                    summary["next"] = (
                        "No action required; delivery is already landed."
                    )
            runnability = summary.get("user_runnability")
            if isinstance(runnability, dict) and runnability.get("status") == "deferred":
                try:
                    from harness.runnability_disposition import read_runnability_disposition

                    disposition = read_runnability_disposition(spec_dir)
                    if disposition is not None and disposition.status == "deferred":
                        runnability["proposal"] = str(
                            spec_dir / disposition.follow_up_proposal
                        )
                except Exception:
                    pass
            try:
                from harness.harness_run_history import summarize_history

                history = summarize_history(spec_dir, limit=1)
                summary["history_count"] = int(history.get("count") or 0)
                recent = history.get("recent")
                if isinstance(recent, list) and recent:
                    latest = recent[-1]
                    if isinstance(latest, dict):
                        summary["last_finished_at"] = str(latest.get("finished_at") or "")
            except Exception:
                pass
    except Exception:
        pass
    return summary


def _delivery_status_fields(summary: dict) -> list[tuple[str, str]]:
    status_icon = {
        "converged": "ok",
        "blocked": "blocked",
        "running": "running",
        "initialized": "initialized",
        "failed": "failed",
        "interrupted": "interrupted",
    }.get(str(summary.get("status") or ""), "status")
    fields: list[tuple[str, str]] = [
        ("spec", str(summary.get("spec_id") or "-")),
        ("build", str(summary.get("build_id") or "-")),
        ("status", f"{status_icon}: {summary.get('status') or 'unknown'}"),
    ]
    if summary.get("spec_status"):
        fields.append(("spec status", str(summary["spec_status"])))
    if summary.get("target"):
        fields.append(("target", str(summary["target"])))
    if summary.get("mode"):
        fields.append(("mode", str(summary["mode"])))
    if summary.get("execution"):
        fields.append(("execution", str(summary["execution"])))
    fields.append(("iteration", f"{summary.get('outer_iter', 0)}.{summary.get('inner_iter', 0)}"))
    convergence = summary.get("convergence")
    if isinstance(convergence, dict):
        fields.extend(
            [
                (
                    "meaningful attempts",
                    f"{convergence.get('meaningful_attempts', 0)} / "
                    f"{convergence.get('hard_ceiling', 0)}",
                ),
                (
                    "stall patience",
                    f"{convergence.get('stalled_attempts', 0)} / "
                    f"{convergence.get('stall_patience', 0)}",
                ),
                (
                    "excluded infra",
                    str(convergence.get("infrastructure_attempts", 0)),
                ),
            ]
        )
        outcome = str(convergence.get("last_outcome") or "").strip()
        reason = str(convergence.get("last_reason") or "").strip()
        if outcome:
            fields.append(("convergence", f"{outcome}: {reason}" if reason else outcome))
        checkpoint = str(convergence.get("best_checkpoint_commit") or "").strip()
        if checkpoint:
            fields.append(("best checkpoint", checkpoint[:12]))
    tokens = int(summary.get("tokens_used") or 0)
    budget = summary.get("token_budget")
    if budget:
        try:
            budget_int = int(budget)
            pct = (tokens / budget_int) * 100 if budget_int else 0
            fields.append(("tokens", f"{tokens:,} / {budget_int:,} ({pct:.0f}%)"))
        except (TypeError, ValueError):
            fields.append(("tokens", f"{tokens:,}"))
    else:
        fields.append(("tokens", f"{tokens:,}"))
    for key, label in (
        ("termination_reason", "reason"),
        ("build_status", "build status"),
        ("build_reason", "build reason"),
        ("pr_url", "PR"),
        ("target_branch", "target branch"),
        ("target_commit", "target commit"),
        ("salvage_branch", "salvage branch"),
        ("salvage_commit", "salvage commit"),
    ):
        value = str(summary.get(key) or "").strip()
        if value:
            fields.append((label, value[:12] if key.endswith("_commit") else value))
    publication_failure = summary.get("publication_failure")
    if isinstance(publication_failure, dict):
        stage = str(publication_failure.get("stage") or "").strip()
        error = str(publication_failure.get("error") or "").strip()
        if stage:
            fields.append(("publish stage", stage))
        if error:
            fields.append(("publish error", error))
    playwright = summary.get("playwright")
    if isinstance(playwright, dict):
        fields.append(
            (
                "sandbox journey",
                (
                    f"{playwright.get('passed', 0)} passed, "
                    f"{playwright.get('failed', 0)} failed, "
                    f"{playwright.get('skipped', 0)} skipped"
                ),
            )
        )
    visual_evidence = summary.get("visual_evidence")
    if isinstance(visual_evidence, dict):
        visual_status = "passed" if visual_evidence.get("passed") else "failed"
        fields.append(
            (
                "visual artifacts",
                f"{visual_evidence.get('artifact_count', 0)} retained ({visual_status})",
            )
        )
        visual_path = str(visual_evidence.get("path") or "").strip()
        if visual_path:
            fields.append(("visual evidence", visual_path))
    local_verification = summary.get("local_verification")
    if isinstance(local_verification, dict):
        fields.append(
            ("local verification", str(local_verification.get("status") or "unknown"))
        )
        runner = str(local_verification.get("runner") or "").strip()
        if runner:
            fields.append(("local runner", runner))
        evidence = str(local_verification.get("evidence") or "").strip()
        if evidence:
            fields.append(("local evidence", evidence))
        latest_status = str(local_verification.get("last_attempt") or "").strip()
        if latest_status:
            fields.append(("last local attempt", latest_status))
        latest_evidence = str(local_verification.get("last_attempt_evidence") or "").strip()
        if latest_evidence and latest_evidence != evidence:
            fields.append(("last local evidence", latest_evidence))
        reason = str(local_verification.get("reason") or "").strip()
        if reason:
            fields.append(("local reason", reason))
    escalation = summary.get("escalation")
    if isinstance(escalation, dict):
        question = str(escalation.get("question") or "").strip()
        context = str(escalation.get("context") or "").strip()
        if question:
            fields.append(("question", question))
        if context:
            fields.append(("context", context))
        choices = escalation.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                label = str(choice.get("label") or "Suggested answer").strip()
                answer = str(choice.get("answer") or "").strip()
                consequence = str(choice.get("consequence") or "").strip()
                marker = " (recommended)" if choice.get("recommended") else ""
                if answer:
                    details = answer
                    if consequence:
                        details += f" — {consequence}"
                    fields.append((f"choice{marker}", f"{label}: {details}"))
        path = str(escalation.get("path") or "").strip()
        if path:
            fields.append(("escalation", path))
    runnability = summary.get("user_runnability")
    if isinstance(runnability, dict):
        status = str(runnability.get("status") or "unknown")
        label = {
            "runnable": "passed",
            "not_runnable": "failed",
            "blocked": "blocked",
            "deferred": "deferred",
            "not_applicable": "not applicable",
        }.get(status, status)
        fields.append(("user runnable", label))
        failed_stage = str(runnability.get("failed_stage") or "").strip()
        if failed_stage:
            fields.append(("stage", failed_stage.replace("_", " ")))
        failure_class = str(runnability.get("failure_class") or "").strip()
        if failure_class:
            fields.append(("runnability reason", failure_class))
        diagnostic = str(runnability.get("summary") or "").strip()
        if diagnostic:
            fields.append(("runnability summary", diagnostic))
        commands = runnability.get("user_commands")
        if isinstance(commands, dict):
            for command_kind in (
                "prerequisites",
                "install",
                "provision",
                "bootstrap",
                "start",
                "open",
                "stop",
            ):
                values = commands.get(command_kind)
                if isinstance(values, list) and values:
                    fields.append((command_kind, "; ".join(str(value) for value in values)))
        local_journey = runnability.get("local_journey")
        if isinstance(local_journey, dict):
            local_status = str(local_journey.get("status") or "unknown").strip()
            fields.append(("local journey", local_status))
            local_reason = str(local_journey.get("reason") or "").strip()
            if local_reason:
                fields.append(("local reason", local_reason))
            local_commands = local_journey.get("commands")
            if isinstance(local_commands, dict):
                for command_kind in (
                    "prerequisites",
                    "provision",
                    "readiness",
                    "prepare",
                    "session",
                    "verify",
                    "start",
                    "open",
                    "stop",
                    "cleanup",
                ):
                    values = local_commands.get(command_kind)
                    if isinstance(values, list) and values:
                        fields.append(
                            (
                                f"local {command_kind}",
                                "; ".join(str(value) for value in values),
                            )
                        )
            boundary_probes = local_journey.get("boundary_probes")
            if isinstance(boundary_probes, list):
                for probe in boundary_probes:
                    if not isinstance(probe, dict):
                        continue
                    probe_id = str(probe.get("id") or "boundary").strip()
                    command = str(probe.get("command") or "").strip()
                    if command:
                        fields.append(("local boundary", f"{probe_id}: {command}"))
        report = str(runnability.get("report") or "").strip()
        if report:
            fields.append(("evidence", report))
        if status == "not_runnable":
            fields.append(
                ("runnability next", "delivery will repair this current-spec product gap")
            )
        elif status == "blocked":
            fields.append(
                ("runnability next", "repair the Echelon sandbox prerequisite, then retry")
            )
        elif status == "deferred":
            proposal = str(runnability.get("proposal") or "").strip()
            fields.append(
                (
                    "runnability next",
                    f"review the advisory follow-up proposal: {proposal}"
                    if proposal
                    else "review the owner-approved runnability deferral",
                )
            )
    coverage_observation = summary.get("coverage_observation")
    if isinstance(coverage_observation, dict):
        observed = int(coverage_observation.get("requirements_observed") or 0)
        total = int(coverage_observation.get("requirements_total") or 0)
        coverage_status = str(coverage_observation.get("status") or "unknown")
        fields.append(
            (
                "coverage",
                f"{observed} / {total} requirements observed ({coverage_status})",
            )
        )
        observers = coverage_observation.get("observers")
        if isinstance(observers, dict):
            for observer_id, observer in sorted(observers.items()):
                if not isinstance(observer, dict):
                    continue
                passed = int(observer.get("passed") or 0)
                total_runs = int(observer.get("total") or 0)
                fields.append(
                    ("observer", f"{observer_id}: {passed}/{total_runs} passed")
                )
        if coverage_observation.get("fingerprint_tuple_complete") is True:
            fields.append(
                (
                    "evidence",
                    "product + map + stack + observer-plan + contract match (recorded candidate)",
                )
            )
    checkpoint_count = int(summary.get("checkpoint_count") or 0)
    if checkpoint_count:
        fields.append(("checkpoints", str(checkpoint_count)))
    history_count = summary.get("history_count")
    if history_count is not None:
        fields.append(("history", f"{history_count} delivery run(s) recorded"))
    if summary.get("state_file"):
        fields.append(("state", str(summary["state_file"])))
    fields.append(("next", str(summary.get("next") or "")))
    return fields


def _normalized_delivery_runnability(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    status = str(value.get("status") or "").strip()
    if not status:
        return None
    raw_commands = value.get("user_commands")
    commands: dict[str, list[str]] = {}
    if isinstance(raw_commands, dict):
        for key, raw_values in raw_commands.items():
            if not isinstance(raw_values, list):
                continue
            normalized = [str(item).strip() for item in raw_values if str(item).strip()]
            if normalized:
                commands[str(key)] = normalized
    local_journey: dict[str, object] | None = None
    raw_local_journey = value.get("local_journey")
    if isinstance(raw_local_journey, dict):
        local_status = str(raw_local_journey.get("status") or "").strip()
        local_commands: dict[str, list[str]] = {}
        raw_local_commands = raw_local_journey.get("commands")
        if isinstance(raw_local_commands, dict):
            for key, raw_values in raw_local_commands.items():
                if not isinstance(raw_values, list):
                    continue
                normalized = [
                    str(item).strip()
                    for item in raw_values
                    if str(item).strip()
                ]
                if normalized:
                    local_commands[str(key)] = normalized
        if local_status:
            boundary_probes: list[dict[str, str]] = []
            raw_boundary_probes = raw_local_journey.get("boundary_probes")
            if isinstance(raw_boundary_probes, list):
                for raw_probe in raw_boundary_probes:
                    if not isinstance(raw_probe, dict):
                        continue
                    command = str(raw_probe.get("command") or "").strip()
                    if not command:
                        continue
                    boundary_probes.append(
                        {
                            "id": str(raw_probe.get("id") or "").strip(),
                            "service": str(raw_probe.get("service") or "").strip(),
                            "command": command,
                        }
                    )
            local_journey = {
                "status": local_status,
                "reason": str(raw_local_journey.get("reason") or "").strip(),
                "commands": local_commands,
                **(
                    {"boundary_probes": boundary_probes}
                    if boundary_probes
                    else {}
                ),
            }
    diagnostic = str(value.get("summary") or "").strip()
    if len(diagnostic) > 240:
        diagnostic = diagnostic[:237].rstrip() + "..."
    return {
        "status": status,
        "failed_stage": str(value.get("failed_stage") or "").strip() or None,
        "failure_class": str(value.get("failure_class") or "").strip(),
        "summary": diagnostic,
        "report": str(value.get("report") or "").strip(),
        "candidate_fingerprint": str(value.get("candidate_fingerprint") or "").strip(),
        "contract_hash": str(value.get("contract_hash") or "").strip(),
        "stack_hash": str(value.get("stack_hash") or "").strip(),
        "user_commands": commands,
        **({"local_journey": local_journey} if local_journey is not None else {}),
        **(
            {"proposal": str(value.get("proposal") or "").strip()}
            if value.get("proposal")
            else {}
        ),
    }

def _normalized_delivery_coverage_observation(value: object) -> dict[str, object] | None:
    """Normalize Ralph's strict coverage state for stable operator reporting."""
    if not isinstance(value, dict):
        return None
    status = str(value.get("status") or "").strip()
    if not status:
        return None
    observed = _nonnegative_delivery_count(value.get("requirements_observed"))
    total = _nonnegative_delivery_count(value.get("requirements_total"))
    observers: dict[str, dict[str, int]] = {}
    raw_observers = value.get("observers")
    if isinstance(raw_observers, dict):
        for raw_id, raw_observer in sorted(raw_observers.items()):
            if not isinstance(raw_observer, dict):
                continue
            observer_id = str(raw_id).strip()
            if not observer_id:
                continue
            execution_count = _nonnegative_delivery_count(
                raw_observer.get("execution_count")
            )
            passed = (
                execution_count
                if str(raw_observer.get("status") or "").strip() == "passed"
                else 0
            )
            observers[observer_id] = {
                "passed": passed,
                "total": execution_count,
            }
    raw_fingerprints = value.get("fingerprints")
    fingerprints: dict[str, str] = {}
    if isinstance(raw_fingerprints, dict):
        for key in (
            "candidate_fingerprint",
            "coverage_map_hash",
            "resolved_stack_hash",
            "observer_plan_hash",
            "runnability_contract_hash",
        ):
            item = str(raw_fingerprints.get(key) or "").strip()
            if item:
                fingerprints[key] = item
    fingerprint_tuple_complete = status == "passed" and len(fingerprints) == 5
    return {
        "status": status,
        "requirements_observed": observed,
        "requirements_total": total,
        "observers": observers,
        "fingerprints": fingerprints,
        "fingerprint_tuple_complete": fingerprint_tuple_complete,
    }

def _nonnegative_delivery_count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def land_delivery(project_root: Path, request: DeliveryLandRequest) -> None:
    """Land one delivery from values already normalized by the Typer boundary."""
    args = [request.spec_id, *request.extra_args]
    if request.continue_existing:
        args.append("--continue")
    if request.prepare_only:
        args.append("--prepare-only")
    if not request.autoresolve:
        args.append("--no-autoresolve")
    if request.allow_fulfillment_gaps:
        args.append("--allow-fulfillment-gaps")
    if request.strategy is not None:
        args.extend(["--strategy", request.strategy])
    _cmd_land(args, project_root=project_root)


def _archive_squad_run(project_dir: Path, spec_id: str) -> None:
    """Offer to archive the active spec run into specs/<spec_id>-*/run/."""
    import shutil
    from echelon.cli import _find_current_run_dir
    from harness.spec_frontmatter import find_spec_dir

    run_dir = _find_current_run_dir(project_dir)
    if run_dir is None:
        return

    spec_dir = find_spec_dir(spec_id, project_dir)
    if spec_dir is None:
        print(f"  (spec run archive skipped — spec {spec_id!r} dir not found)", flush=True)
        return

    run_id = run_dir.name
    archive_dest = spec_dir / "run"
    current_marker = run_dir.parent / ".current"
    try:
        spec_rel = spec_dir.resolve().relative_to(project_dir.resolve())
    except ValueError:
        spec_rel = spec_dir
    print(
        f"\nArchive spec run {run_id!r} into "
        f"{spec_rel}/run/ ?"
    )
    if not sys.stdin.isatty():
        print("  Spec run archive skipped — non-interactive stdin.", flush=True)
        return
    try:
        choice = input("  [Y]es archive / [n]o keep in runs/ / [s]kip: ").strip().lower()
    except EOFError:
        print("  Spec run archive skipped — no input available.", flush=True)
        return

    if choice in ("", "y", "yes"):
        shutil.move(str(run_dir), str(archive_dest))
        if current_marker.exists():
            current_marker.unlink()
        import subprocess
        subprocess.run(["git", "add", str(archive_dest)], cwd=str(project_dir), check=False)
        subprocess.run(
            ["git", "rm", "-r", "--cached", str(run_dir)],
            cwd=str(project_dir), check=False, capture_output=True,
        )
        try:
            archive_rel = archive_dest.resolve().relative_to(project_dir.resolve())
        except ValueError:
            archive_rel = archive_dest
        print(f"  ✓ Archived to {archive_rel}", flush=True)
    elif choice in ("s", "skip"):
        print("  Skipped.", flush=True)
    else:
        run_rel = run_dir.relative_to(project_dir) if run_dir.is_relative_to(project_dir) else run_dir
        print(f"  Spec run left at {run_rel}/", flush=True)


def _print_harness_config_error(error: Exception) -> None:
    field_path = getattr(error, "field_path", None)
    if field_path == "target_repo":
        print(f"✗ Harness config error: {error}", file=sys.stderr)
        return
    print(f"✗ Harness config error: {error}\n  Fix: re-run 'echelon delivery init'.", file=sys.stderr)


def _cmd_land(
    args: list[str],
    *,
    project_root: Path | None = None,
) -> None:
    """Land a spec: merge PR, delete branch, clean worktrees, mark done."""
    import logging
    from echelon.cli import (
        _banner,
        _command_display,
        _require_provider_capability,
    )

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: echelon delivery land <spec_id> [--continue] [--prepare-only] "
            "[--no-autoresolve] [--allow-fulfillment-gaps] "
            "[--strategy merge|rebase]\n\n"
            "  Compatibility alias: echelon land <spec_id> [options...]\n"
            "  Merge PR, delete branch, clean worktrees, mark spec as landed.\n",
        )
        sys.exit(0)

    if args[0].startswith("-"):
        print(f"✗ missing spec_id before option {args[0]!r}", file=sys.stderr)
        sys.exit(1)

    spec_id = args[0]
    continue_existing = False
    prepare_only = False
    autoresolve = True
    allow_fulfillment_gaps = False
    strategy = "merge"

    remaining = args[1:]
    idx = 0
    while idx < len(remaining):
        arg = remaining[idx]
        if arg == "--continue":
            continue_existing = True
        elif arg == "--prepare-only":
            prepare_only = True
        elif arg == "--no-autoresolve":
            autoresolve = False
        elif arg == "--allow-fulfillment-gaps":
            allow_fulfillment_gaps = True
        elif arg == "--strategy":
            if idx + 1 >= len(remaining):
                print("✗ --strategy requires 'merge' or 'rebase'", file=sys.stderr)
                sys.exit(1)
            strategy = remaining[idx + 1]
            idx += 1
        elif arg.startswith("-"):
            print(f"✗ unknown option for echelon delivery land: {arg}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"✗ unexpected argument for echelon delivery land: {arg}", file=sys.stderr)
            sys.exit(1)
        idx += 1

    if strategy not in {"merge", "rebase"}:
        print("✗ --strategy must be 'merge' or 'rebase'", file=sys.stderr)
        sys.exit(1)

    project_dir = project_root or Path.cwd()
    target_env = os.environ.get("ECHELON_TARGET_REPO_PATH")
    polyrepo_env = os.environ.get("ECHELON_POLYREPO_ROOT")
    target_name_env = os.environ.get("ECHELON_TARGET_REPO_NAME")
    config_root = Path(polyrepo_env).resolve() if target_env and polyrepo_env else project_dir
    _require_provider_capability(
        "echelon delivery land",
        ProviderCapability.BUILD,
        project_dir=config_root,
    )
    harness_base_dir = project_dir
    if target_env and polyrepo_env:
        harness_base_dir = (
            config_root
            / "runs"
            / "targets"
            / (target_name_env or Path(target_env).resolve().name)
        )
        _sync_polyrepo_runtime_extension(config_root, harness_base_dir)
        project_dir = config_root
    elif _dispatch_land_to_spec_targets(
        spec_id,
        args[1:],
        project_root=project_dir,
        rerun_command=_command_display("echelon delivery land", args),
    ):
        return

    from harness.config import load_config, ValidationError as HarnessValidationError
    from harness.gitops import GitOpsManager
    from harness.land import LandOptions, land
    from harness.paths import mirror_path as _mirror_path_fn
    options = LandOptions(
        autoresolve=autoresolve,
        prepare_only=prepare_only,
        continue_existing=continue_existing,
        allow_fulfillment_gaps=allow_fulfillment_gaps,
    )

    try:
        config = (
            load_config(project_root=config_root, squad_only=True)
            if target_env
            else load_config(project_root=config_root)
        )
    except HarnessValidationError as e:
        _print_harness_config_error(e)
        sys.exit(1)
    if target_env:
        target_repo_path = Path(target_env).resolve()
        config.target_repo = str(target_repo_path)
        if not getattr(config, "target_default_branch", None):
            config.target_default_branch = "main"
        if getattr(config, "provider", None) not in {"docker", "e2b", "modal", "daytona"}:
            config.provider = "docker"
    gitops = GitOpsManager(config, base_dir=str(harness_base_dir))
    if target_env and not _mirror_path_fn(harness_base_dir).exists():
        gitops.clone_mirror(config.target_repo)

    land_kwargs = (
        {"harness_root": harness_base_dir}
        if target_env and polyrepo_env
        else {}
    )
    success = land(
        spec_id,
        project_dir=project_dir,
        gitops=gitops,
        options=options,
        **land_kwargs,
    )
    if success:
        if options.prepare_only:
            _banner("LAND", [("spec", spec_id), ("status", "prepared")])
            sys.exit(0)
        _banner("LAND", [("spec", spec_id), ("status", "landed successfully")])
        _archive_squad_run(project_dir, spec_id)
        sys.exit(0)
    else:
        _banner(
            "LAND",
            [
                ("spec", spec_id),
                ("status", "could not be landed; see the specific blocker above"),
            ],
            file=sys.stderr,
        )
        sys.exit(1)


def _dispatch_land_to_spec_targets(
    spec_id: str,
    extra_args: list[str],
    *,
    project_root: Path,
    rerun_command: str,
) -> bool:
    """Dispatch workspace-level land to target repos declared by the spec."""
    from harness.spec_frontmatter import find_spec_dir, read_targets, write_targets
    from echelon.orchestrator import run_multi_target, validate_single_target, validate_targets

    spec_dir = find_spec_dir(spec_id, project_root)
    if spec_dir is None:
        return False
    targets_rel = read_targets(spec_dir)
    if not targets_rel:
        return False

    resolved_spec_id = spec_dir.name
    polyrepo_root = spec_dir.parent.parent
    if len(targets_rel) == 1:
        workspace_target = _resolve_harness_workspace_target(
            polyrepo_root,
            targets_rel[0],
            spec_dir=spec_dir,
            spec_id=resolved_spec_id,
            rerun_command=rerun_command,
        )
        if workspace_target.source_root == workspace_target.workspace_root:
            return False
        target_rel = workspace_target.source_root.relative_to(
            workspace_target.workspace_root
        ).as_posix()
        if target_rel != targets_rel[0]:
            write_targets(spec_dir, [target_rel])
        target = validate_single_target([target_rel], polyrepo_root)
        sys.exit(
            run_multi_target(
                resolved_spec_id,
                [target],
                extra_args,
                command="land",
                **_workspace_target_dispatch_metadata(workspace_target),
            )
        )

    targets = validate_targets(targets_rel, polyrepo_root)
    source_ids: dict[str, str] = {}
    source_git_roles: dict[str, str] = {}
    for target in targets:
        target_metadata = _source_dispatch_metadata(
            target=target,
            polyrepo_root=polyrepo_root,
            source_id=None,
        )
        source_ids.update(target_metadata["source_ids"])
        source_git_roles.update(target_metadata["source_git_roles"])
    sys.exit(
        run_multi_target(
            resolved_spec_id,
            targets,
            extra_args,
            command="land",
            workspace_root=polyrepo_root.resolve(),
            workspace_git_role="orchestration",
            source_ids=source_ids,
            source_git_roles=source_git_roles,
        )
    )


def _print_missing_spec_target_error(
    spec_id: str,
    *,
    command_prefix: str = "echelon delivery run",
) -> None:
    print(
        f"✗ Spec '{spec_id}' has no implementation target.\n\n"
        "  Implementation targets are fixed when Phase A begins. Start a new spec run with:\n"
        "    echelon spec run <description> --target <source-path> "
        "[--target <source-path> ...]\n\n"
        f"  Delivery will not infer or mutate targets for spec '{spec_id}'.",
        file=sys.stderr,
    )


def _block_if_spec_task_targets_mismatch(
    spec_dir: Path,
    declared_targets: list[str],
    spec_id: str,
) -> None:
    """Fail before delivery spends tokens on tasks owned by other source repos."""
    tasks_path = spec_dir / "tasks.md"
    if not tasks_path.is_file() or not declared_targets:
        return

    from harness.task_targets import validate_task_targets

    result = validate_task_targets(
        tasks_path.read_text(encoding="utf-8", errors="replace"),
        declared_targets=declared_targets,
    )
    if result.valid:
        return

    lines = [
        "✗ Task ownership does not match the spec delivery targets.",
        "",
        "  Delivery is stopping before launching a build agent.",
        "  declared: " + ", ".join(declared_targets),
    ]
    if result.missing_targets:
        lines.append("  missing targets: " + ", ".join(result.missing_targets))
    if result.unreferenced_targets:
        lines.append(
            "  unreferenced targets: " + ", ".join(result.unreferenced_targets)
        )
    if result.unowned_tasks:
        lines.append(
            "  tasks without explicit target= ownership: "
            + ", ".join(result.unowned_tasks)
        )
    if result.cross_target_tasks:
        rendered = ", ".join(
            f"{task_id} ({' + '.join(targets)})"
            for task_id, targets in result.cross_target_tasks.items()
        )
        lines.append("  tasks spanning multiple targets: " + rendered)
    if result.path_target_mismatches:
        rendered = ", ".join(
            f"{task_id} (target={declared}; paths={' + '.join(paths)})"
            for task_id, (declared, paths) in result.path_target_mismatches.items()
        )
        lines.append("  task target/path mismatches: " + rendered)

    lines.extend(
        [
            "",
            "  Every task must declare exactly one target=<source-path> from targets.yml.",
            "  File paths validate ownership but never infer or replace it.",
        ]
    )
    lines.append(
        "  Regenerate target-dependent plan/tasks artifacts from a correctly targeted spec run."
    )
    print("\n".join(lines), file=sys.stderr)
    raise SystemExit(2)


def initialize_delivery(
    project_root: Path,
    *,
    extra_args: Sequence[str] = (),
) -> None:
    import logging

    from echelon.cli import (
        _banner,
        _command_display,
        _project_echelon_config,
        _require_provider_capability,
        _workspace_git_preflight,
    )
    from echelon.workspace_service import (
        _assert_local_config_untracked,
        _ensure_local_config_ignored,
    )

    command_prefix = "echelon delivery init"
    args = list(extra_args)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args:
        print(
            f"✗ {command_prefix} no longer accepts a target repository.\n\n"
            "  Implementation targets are declared when Phase A begins:\n"
            "    echelon spec run <description> --target <source-path> "
            "[--target <source-path> ...]\n\n"
            f"  Then rerun: {command_prefix}",
            file=sys.stderr,
        )
        sys.exit(1)

    _require_provider_capability(
        command_prefix,
        ProviderCapability.BUILD,
        project_dir=project_root,
    )

    target_repo = "."
    base_dir = str(project_root)
    _workspace_git_preflight(
        project_root,
        command_name=_command_display(command_prefix, args),
    )
    bind_mount_ack = os.environ.get("HARNESS_BIND_MOUNT_ACK", "").lower() in (
        "true",
        "1",
        "yes",
    )
    try:
        _assert_local_config_untracked(project_root)
    except ValueError as exc:
        print(f"✗ {command_prefix} failed: {exc}", file=sys.stderr)
        sys.exit(1)

    from harness.init import InitError, init_harness

    try:
        config = init_harness(
            target_repo=target_repo,
            base_dir=base_dir,
            bind_mount_ack=bind_mount_ack,
        )
    except InitError as exc:
        print(f"✗ {command_prefix} failed: {exc}", file=sys.stderr)
        sys.exit(1)

    _ensure_local_config_ignored(project_root)

    config_file = _project_echelon_config(project_root)
    from harness.paths import mirror_path as _mirror_path_fn

    mirror_dir = _mirror_path_fn(project_root)

    image_note = ""
    if config.base_image is None:
        try:
            import yaml as _yaml

            raw = _yaml.safe_load(config_file.read_text())
            harness_raw = raw.get("harness", raw)
            detected = harness_raw.get("detected_image", "ubuntu:22.04")
            source = harness_raw.get("detected_image_source", "fallback")
            if source == "fallback":
                image_note = (
                    "\n  ⚠  base_image not detected — using ubuntu:22.04 as fallback.\n"
                    f"     Set base_image in {config_file}\n"
                    "     once you know your stack (e.g. node:20, python:3.12-slim).\n"
                )
            else:
                image_note = (
                    f"\n  base_image    → {detected} (auto-detected: {source})\n"
                )
        except Exception:
            pass

    fields = [
        ("Config", str(config_file)),
        ("Mirror", str(mirror_dir)),
        ("Provider", config.provider),
        ("PR host", config.pr_host),
    ]
    if image_note.strip():
        fields.append(("Base image", image_note.strip()))
    fields.extend(_harness_init_detection_fields(config_file))
    fields.append(("Next step", _harness_init_next_step(config_file)))
    _banner("HARNESS INIT — COMPLETE", fields)


def prepare_target(project_root: Path, *, spec_id: str) -> None:
    from echelon.cli import _banner, _require_provider_capability
    from harness.spec_frontmatter import (
        find_spec_dir,
        read_target_entries,
        write_target_delivery,
    )

    _require_provider_capability(
        "echelon delivery target",
        ProviderCapability.BUILD,
        project_dir=project_root,
    )
    spec_dir = find_spec_dir(spec_id, project_root)
    if spec_dir is None:
        print(
            f"✗ Spec {spec_id!r} not found (searched from {project_root})",
            file=sys.stderr,
        )
        sys.exit(1)

    targets = read_target_entries(spec_dir)
    if not targets:
        print(
            f"✗ Spec {spec_dir.name} has no delivery target.\n"
            "  Delivery will not infer or mutate targets. Regenerate the spec with "
            "echelon spec run <description> --target <source-path>.",
            file=sys.stderr,
        )
        sys.exit(1)

    _block_if_spec_task_targets_mismatch(
        spec_dir,
        [str(entry.get("path") or "").strip() for entry in targets],
        spec_dir.name,
    )

    spec_root = spec_dir.parent.parent
    fields: list[tuple[str, str]] = [("Spec", spec_dir.name)]
    for entry in targets:
        target_rel = str(entry.get("path") or "").strip()
        if not target_rel:
            continue
        target_path = Path(target_rel).expanduser()
        if not target_path.is_absolute():
            target_path = (spec_root / target_path).resolve()
        if not target_path.exists():
            print(
                f"✗ Target repo not found: {target_rel}\n"
                "  Restore the declared repo, or regenerate the spec with "
                f"--target {target_rel} --init.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not (target_path / ".git").exists():
            print(
                f"✗ Target is not a Git repo: {target_rel}\n"
                "  Initialize the declared repo, or regenerate the spec with "
                f"--target {target_rel} --init.",
                file=sys.stderr,
            )
            sys.exit(1)

        delivery = _detect_target_verify_delivery(target_path, spec_dir.name)
        write_target_delivery(spec_dir, target_rel, delivery)
        fields.append(("Target", target_rel))
        fields.append(("Branch", str(entry.get("branch") or spec_dir.name)))
        verify = delivery.get("verify_command")
        if verify:
            fields.append(("Verify", str(verify)))
        else:
            reason = (
                delivery.get("verify_reason")
                or "no high-confidence verify command detected"
            )
            fields.append(("Verify", f"not configured - {reason}"))

    fields.append(("Metadata", str(spec_dir / "targets.yml")))
    fields.append(("Next", f"echelon delivery run {spec_dir.name} --mode=banzai"))
    _banner("DELIVERY TARGET", fields)


def _harness_verify_status(config_file: Path) -> tuple[str, str, str]:
    """Return (verify_command, detection_status, detection_reason)."""
    try:
        import yaml as _yaml

        raw = _yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return "", "", ""

    if not isinstance(raw, dict):
        return "", "", ""
    harness_raw = raw.get("harness", {})
    if not isinstance(harness_raw, dict):
        harness_raw = {}

    return (
        str(raw.get("verify_command") or ""),
        str(harness_raw.get("verify_command_detection") or ""),
        str(harness_raw.get("verify_command_reason") or ""),
    )


def _harness_init_next_step(config_file: Path) -> str:
    """Return the init banner next step without suggesting an invalid delivery run."""
    verify_command, verify_detection, verify_reason = _harness_verify_status(config_file)
    if verify_command:
        return 'echelon spec run "<feature>"\n  echelon delivery run <spec_id>'

    if verify_detection or verify_reason:
        detail = verify_detection or "none"
        if verify_reason:
            detail += f": {verify_reason}"
        return (
            "set top-level verify_command before delivery build\n"
            f"  detection: {detail}\n"
            "  examples:\n"
            "    verify_command: pytest\n"
            "    verify_command: npm test\n"
            "    verify_command: go test ./...\n"
            "  then: echelon delivery continue <spec_id>  # if recovering a blocked run\n"
            "        echelon delivery run <spec_id>     # for a new build"
        )

    return (
        'echelon spec run "<feature>"\n'
        "  echelon delivery run <spec_id>\n"
        "  if verification blocks: echelon delivery init or set verify_command manually"
    )


def _harness_init_detection_fields(config_file: Path) -> list[tuple[str, str]]:
    """Summarize auto-detected harness commands for the init banner."""
    try:
        import yaml as _yaml

        raw = _yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return []

    harness_raw = raw.get("harness", {})
    if not isinstance(harness_raw, dict):
        harness_raw = {}

    fields: list[tuple[str, str]] = []
    verify_command = raw.get("verify_command")
    verify_detection = harness_raw.get("verify_command_detection")
    verify_reason = harness_raw.get("verify_command_reason")
    if verify_command:
        source = "auto-detected" if verify_detection == "high" else "configured"
        fields.append(("Verify", f"{verify_command} ({source})"))
    elif verify_detection or verify_reason:
        status = str(verify_detection or "none")
        detail = f"{status}: {verify_reason}" if verify_reason else status
        fields.append(("Verify", f"not configured - {detail}"))

    app_raw = harness_raw.get("app")
    app_detection = harness_raw.get("app_detection")
    app_reason = harness_raw.get("app_reason")
    if isinstance(app_raw, dict) and app_raw:
        mode = app_raw.get("mode", "manual")
        app_name = (
            app_raw.get("app")
            or app_raw.get("service")
            or app_raw.get("compose_file")
            or "app"
        )
        url = app_raw.get("url")
        source = "auto-detected" if app_detection == "high" else "configured"
        detail = f"{app_name} via {mode}"
        if url:
            detail += f" at {url}"
        fields.append(("App runtime", f"{detail} ({source})"))
    elif app_detection or app_reason:
        status = str(app_detection or "none")
        detail = f"{status}: {app_reason}" if app_reason else status
        fields.append(("App runtime", f"not configured - {detail}"))

    sandbox_raw = harness_raw.get("sandbox_suggestion")
    if isinstance(sandbox_raw, dict) and sandbox_raw:
        confidence = sandbox_raw.get("confidence", "unknown")
        score = sandbox_raw.get("confidence_score", 0.0)
        strategy = sandbox_raw.get(
            "suggested_strategy", "review sandbox suggestion"
        )
        approval = sandbox_raw.get(
            "human_approval_point", "review before execution"
        )
        fields.append(
            (
                "Sandbox",
                f"{confidence} ({float(score):.2f}) - {strategy} Approval: {approval}",
            )
        )
        fields.append(
            ("Sandbox report", str(config_file.with_name("sandbox-suggestion.md")))
        )

    return fields


def _format_missing_verify_command_resume_message(
    config_file: Path,
    spec_id: str,
) -> str:
    """Format actionable resume guidance when verify_command is still missing."""
    _verify_command, verify_detection, verify_reason = _harness_verify_status(config_file)
    examples = (
        "    verify_command: swift test --package-path Packages/MyLib\n"
        "    verify_command: pytest\n"
        "    verify_command: npm test\n"
        "    verify_command: go test ./..."
    )

    if verify_detection or verify_reason:
        detail = verify_detection or "none"
        if verify_reason:
            detail += f": {verify_reason}"
        return (
            "✗ verify_command is still not set in echelon-config.yml.\n\n"
            "  Auto-detection already ran and did not configure a command.\n"
            f"  detection: {detail}\n\n"
            f"  Add a top-level verify_command to {config_file}, for example:\n"
            f"{examples}\n\n"
            f"  Then re-run:  echelon delivery continue {spec_id}"
        )

    return (
        "✗ verify_command is still not set in echelon-config.yml.\n\n"
        "  Option 1 — auto-detect once:  echelon delivery init\n"
        "  Option 2 — manual:            add a top-level verify_command to echelon-config.yml:\n"
        f"{examples}\n\n"
        f"  Then re-run:  echelon delivery continue {spec_id}"
    )


def _run_git_quiet(
    args: list[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _clean_git_branch_name(line: str) -> str:
    return line.strip().removeprefix("*").strip()


def _target_feature_branch_candidates(target_repo: Path, spec_id: str) -> list[str]:
    if not (target_repo / ".git").exists():
        return []
    result = _run_git_quiet(
        ["branch", "--list", spec_id, f"{spec_id}-*"],
        cwd=target_repo,
    )
    if result.returncode != 0:
        return []
    branches: list[str] = []
    for line in result.stdout.splitlines():
        branch = _clean_git_branch_name(line)
        if branch and branch not in branches:
            branches.append(branch)
    return branches


def _detect_verify_result_from_git_ref(
    target_repo: Path,
    git_ref: str,
) -> object | None:
    import tempfile

    from harness.verify_detection import detect_verify_command

    rev = _run_git_quiet(
        ["rev-parse", "--verify", f"{git_ref}^{{commit}}"],
        cwd=target_repo,
    )
    if rev.returncode != 0:
        return None

    with tempfile.TemporaryDirectory(prefix="echelon-verify-detect-") as tmp:
        worktree = Path(tmp) / "worktree"
        added = _run_git_quiet(
            ["worktree", "add", "--detach", str(worktree), rev.stdout.strip()],
            cwd=target_repo,
        )
        if added.returncode != 0:
            return None
        try:
            detected = detect_verify_command(worktree)
            if detected.confidence == "high" and detected.command:
                return detected
            return None
        finally:
            _run_git_quiet(
                ["worktree", "remove", "--force", str(worktree)],
                cwd=target_repo,
            )
            _run_git_quiet(["worktree", "prune"], cwd=target_repo)


def _detect_verify_command_from_git_ref(
    target_repo: Path,
    git_ref: str,
) -> str | None:
    detected = _detect_verify_result_from_git_ref(target_repo, git_ref)
    command = getattr(detected, "command", None)
    return str(command) if command else None


def _detect_target_verify_delivery(
    target_repo: Path,
    spec_id: str,
) -> dict[str, object]:
    from harness.verify_detection import detect_verify_command

    detected = detect_verify_command(target_repo)
    source = "target_checkout"
    if detected.confidence != "high" or not detected.command:
        for branch in _target_feature_branch_candidates(target_repo, spec_id):
            branch_detected = _detect_verify_result_from_git_ref(target_repo, branch)
            if branch_detected is not None:
                detected = branch_detected  # type: ignore[assignment]
                source = f"branch:{branch}"
                break

    result: dict[str, object] = {
        "verify_detection": str(getattr(detected, "confidence", "none")),
        "verify_source": source,
    }
    command = getattr(detected, "command", None)
    if command:
        result["verify_command"] = str(command)
    evidence = getattr(detected, "evidence", None)
    if isinstance(evidence, list) and evidence:
        result["verify_evidence"] = [str(item) for item in evidence]
    reason = getattr(detected, "reason", None)
    if reason:
        result["verify_reason"] = str(reason)
    return result


def _apply_target_verify_command_detection(
    config: object,
    *,
    target_repo: Path | None,
    spec_id: str,
) -> None:
    """Populate runtime verify_command from the actual delivery target."""
    if getattr(config, "verify_command", None) or target_repo is None:
        return
    if not target_repo.exists():
        return

    from harness.verify_detection import detect_verify_command

    detected = detect_verify_command(target_repo)
    if detected.confidence == "high" and detected.command:
        config.verify_command = detected.command
        print(
            f"Detected verify_command from delivery target: {detected.command}",
            file=sys.stderr,
        )
        return

    for branch in _target_feature_branch_candidates(target_repo, spec_id):
        command = _detect_verify_command_from_git_ref(target_repo, branch)
        if command:
            config.verify_command = command
            print(
                f"Detected verify_command from delivery target branch {branch}: {command}",
                file=sys.stderr,
            )
            return


def _sync_polyrepo_runtime_extension(
    polyrepo_root: Path,
    harness_base_dir: Path,
) -> None:
    """Copy deployed Prosaic and runtime bundles into a target harness base."""
    prose_source = polyrepo_root / ".echelon" / "prosaic"
    runtime_source = polyrepo_root / ".echelon" / "runtime"
    prose_dest = harness_base_dir / ".echelon" / "prosaic"
    runtime_dest = harness_base_dir / ".echelon" / "runtime"
    required = (
        prose_source / "commands",
        prose_source / "subagents",
        runtime_source / "workflow" / "definition.yaml",
    )
    if not all(path.exists() for path in required):
        print(
            "✗ Echelon Prosaic/runtime bundle is not installed in polyrepo root.\n"
            f"  Expected: {prose_source} and {runtime_source}\n"
            "  Fix: run 'echelon workspace migrate-to-prosaic' from the polyrepo root.",
            file=sys.stderr,
        )
        sys.exit(1)
    copy_prosaic_runtime_tree(prose_source, prose_dest)
    copy_runtime_tree(runtime_source, runtime_dest)
    prune_delivery_workflow_definition(runtime_dest / "workflow" / "definition.yaml")


def _target_candidate_lines(candidates: list[object]) -> str:
    lines: list[str] = []
    for candidate in candidates:
        repo = str(getattr(candidate, "repo", ""))
        evidence = [str(item) for item in getattr(candidate, "evidence", [])]
        source_path = None
        for item in evidence:
            prefix = "workspace source path `"
            if item.startswith(prefix) and item.endswith("`"):
                source_path = item[len(prefix) : -1]
                break
        if source_path and source_path != repo:
            lines.append(f"  - {repo} (path: {source_path})")
        elif repo:
            lines.append(f"  - {repo}")
    return "\n".join(lines)


def _source_dispatch_metadata(
    *,
    target: Path,
    polyrepo_root: Path,
    source_id: str | None,
) -> dict[str, object]:
    resolved_target = target.resolve()
    resolved_workspace = polyrepo_root.resolve()
    resolved_source_id = source_id or (
        "." if resolved_target == resolved_workspace else target.name
    )
    workspace_git_role = (
        "source"
        if resolved_target == resolved_workspace and resolved_source_id == "."
        else "orchestration"
    )
    return {
        "workspace_root": resolved_workspace,
        "workspace_git_role": workspace_git_role,
        "source_ids": {str(resolved_target): resolved_source_id},
        "source_git_roles": {str(resolved_target): "source"},
    }


def _resolve_harness_workspace_target(
    project_root: Path,
    explicit_target: str | None,
    *,
    spec_dir: Path | None = None,
    spec_id: str | None = None,
    rerun_command: str | None = None,
) -> HarnessWorkspaceTarget:
    from echelon.target_detection import detect_target
    from echelon.workspace_model import SourceRoot, discover_workspace

    manifest = discover_workspace(project_root)
    if explicit_target == ".":
        return HarnessWorkspaceTarget(
            workspace_root=manifest.workspace.root,
            workspace_git_role="source",
            source_root=manifest.workspace.root,
            source_id=".",
            source_git_role="source",
        )

    result = detect_target(
        spec_dir=spec_dir or project_root,
        polyrepo_root=project_root,
        workspace_manifest=manifest,
        explicit_target=explicit_target,
    )

    def _candidate_lines() -> str:
        return _target_candidate_lines(result.candidates)

    command_label = (
        "delivery"
        if (rerun_command or "").startswith("echelon delivery ")
        else "harness"
    )
    new_repo_hint = (
        "\n\n"
        "  For a new implementation repo:\n"
        "    echelon spec run <description> --target sources/<new-repo> --init"
    )

    if result.decision == "no_source_roots":
        print(
            "✗ No source roots found; harness build needs at least one implementation source root.\n\n"
            "  Add or checkout the source repo(s), or add source project markers to this workspace."
            + (f"\n  Then rerun:  {rerun_command}" if rerun_command else ""),
            file=sys.stderr,
        )
        raise SystemExit(2)

    if result.decision == "multiple_source_roots_need_target":
        print(
            f"✗ Multiple source roots found; choose one before running {command_label}.\n\n"
            "  Source roots:\n"
            f"{_candidate_lines()}\n\n"
            "  Fix: start Phase A with repeatable "
            "'echelon spec run <description> --target <source-path>' options."
            + new_repo_hint
            + (f"\n  Then rerun:  {rerun_command}" if rerun_command else ""),
            file=sys.stderr,
        )
        raise SystemExit(2)

    if result.decision == "invalid_target":
        configured = (
            f"\n  Configured target: {explicit_target}" if explicit_target else ""
        )
        print(
            "✗ Configured implementation target does not match a workspace source root.\n"
            f"{configured}\n\n"
            "  Source roots:\n"
            f"{_candidate_lines()}\n\n"
            "  Fix: regenerate with 'echelon spec run <description> "
            "--target <source-path>'.\n"
            "       For a new repo, add --init."
            + (f"\n  Then rerun:  {rerun_command}" if rerun_command else ""),
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not result.recommended_target:
        print(
            "✗ No implementation target configured and target detection was ambiguous.\n"
            "  Fix: start Phase A with 'echelon spec run <description> "
            "--target <source-path>'.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    source_root = (
        manifest.workspace.root
        if result.recommended_target == "."
        else (manifest.workspace.root / result.recommended_target).resolve()
    )
    source: SourceRoot | None = None
    for candidate in manifest.sources:
        candidate_root = (
            manifest.workspace.root
            if candidate.path == "."
            else (manifest.workspace.root / candidate.path).resolve()
        )
        if candidate_root == source_root:
            source = candidate
            break
    if source is None:
        print(
            "✗ Recommended implementation target does not match a workspace source root.\n"
            f"  Target: {result.recommended_target}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    return HarnessWorkspaceTarget(
        workspace_root=manifest.workspace.root,
        workspace_git_role=manifest.workspace.git_role,
        source_root=source_root,
        source_id=source.id,
        source_git_role=source.git_role,
    )


def _workspace_target_dispatch_metadata(
    target: HarnessWorkspaceTarget,
) -> dict[str, object]:
    return {
        "workspace_root": target.workspace_root,
        "workspace_git_role": target.workspace_git_role,
        "source_ids": {str(target.source_root.resolve()): target.source_id},
        "source_git_roles": {
            str(target.source_root.resolve()): target.source_git_role
        },
    }


def _local_delivery_workspace_root(project_dir: Path) -> Path:
    configured = os.environ.get("ECHELON_POLYREPO_ROOT", "").strip()
    root = Path(configured).expanduser() if configured else Path(project_dir)
    if root.is_symlink():
        raise ValueError("local verification workspace root is symlinked")
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise ValueError("local verification workspace root is unavailable") from exc
    if not root.is_dir():
        raise ValueError("local verification workspace root is unavailable")
    return root


def _resolve_local_delivery_target(
    project_dir: Path,
    spec_id: str,
    requested_target: str | None,
) -> tuple[Path, Path, str, str]:
    """Resolve one declared target; local verification never guesses a target."""
    from harness.spec_frontmatter import find_spec_dir, read_target_entries

    workspace = _local_delivery_workspace_root(project_dir)
    spec_dir = find_spec_dir(spec_id, workspace)
    if spec_dir is None:
        raise ValueError(f"spec {spec_id!r} was not found in this workspace")
    entries = read_target_entries(spec_dir)
    if not entries:
        raise ValueError("spec has no declared delivery target")
    selector = (requested_target or "").strip()
    matches = []
    for entry in entries:
        entry_id = str(entry.get("id") or "").strip()
        path_value = str(entry.get("path") or "").strip()
        if not path_value:
            continue
        if not selector or selector in {entry_id, path_value, Path(path_value).name}:
            matches.append((entry_id, path_value))
    if len(matches) != 1:
        if selector:
            raise ValueError(
                "--target must identify exactly one declared delivery target"
            )
        raise ValueError(
            "spec has multiple delivery targets; rerun with --target <target-id>"
        )
    target_id, target_value = matches[0]
    target = Path(target_value).expanduser()
    if not target.is_absolute():
        target = workspace / target
    if target.is_symlink():
        raise ValueError("local verification target is symlinked")
    try:
        target = target.resolve(strict=True)
    except OSError as exc:
        raise ValueError("local verification target is unavailable") from exc
    if not target.is_dir():
        raise ValueError("local verification target is unavailable")
    return workspace, target, target_id or target.name, spec_dir.name


def _select_local_engine(engine: str) -> str:
    requested = engine.strip().lower()
    if requested not in {"auto", "docker", "podman"}:
        raise ValueError("--engine must be auto, docker, or podman")
    if requested != "auto":
        return requested
    if shutil.which("docker"):
        return "docker"
    if shutil.which("podman"):
        return "podman"
    raise ValueError(
        "no supported local engine found; install Docker Desktop or Podman"
    )


def _local_candidate_fingerprint(candidate: object) -> str:
    fields = (
        "product_fingerprint",
        "contract_hash",
        "stack_hash",
        "observer_plan_hash",
        "sandbox_receipt_sha256",
    )
    payload = {name: str(getattr(candidate, name, "")) for name in fields}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _build_local_action_plan(
    project_dir: Path,
    spec_id: str,
    target_id: str | None,
    engine: str,
    *,
    build_id: str | None = None,
) -> LocalActionPlan:
    """Resolve immutable sandbox evidence before any host resource is created."""
    from harness.local_runner_candidate import (
        LocalCandidateRequest,
        resolve_effective_local_candidate,
    )

    workspace, target, resolved_target_id, resolved_spec_id = (
        _resolve_local_delivery_target(project_dir, spec_id, target_id)
    )
    candidate = resolve_effective_local_candidate(
        LocalCandidateRequest(
            workspace_root=workspace,
            target_root=target,
            spec_id=resolved_spec_id,
            target_id=resolved_target_id,
            build_id=build_id,
        )
    )
    selected_engine = _select_local_engine(engine)
    actions = (
        "materialize the sandbox-approved candidate in a managed detached worktree",
        "start a run-ID-labelled PostgreSQL container on a generated loopback port",
        "run the declared lifecycle in a scrubbed, run-local host environment",
        "observe the browser, restart persistence, and PostgreSQL boundary independently",
        "record a redacted immutable attestation and remove only journalled resources",
    )
    fingerprint = _local_candidate_fingerprint(candidate)
    digest = hashlib.sha256(
        json.dumps(
            {
                "spec_id": resolved_spec_id,
                "target_id": resolved_target_id,
                "engine": selected_engine,
                "candidate_fingerprint": fingerprint,
                "planned_actions": actions,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return LocalActionPlan(
        spec_id=resolved_spec_id,
        target_id=resolved_target_id,
        engine=selected_engine,
        candidate_fingerprint=fingerprint,
        planned_actions=actions,
        digest=digest,
        workspace_root=workspace,
        target_root=target,
        candidate=candidate,
    )


def _confirm_local_action_plan(action_plan: LocalActionPlan) -> None:
    from echelon.cli import _banner

    _banner(
        "LOCAL DELIVERY VERIFICATION",
        [
            ("spec", action_plan.spec_id),
            ("target", action_plan.target_id),
            ("engine", action_plan.engine),
            ("candidate", action_plan.candidate_fingerprint[:12]),
            ("action", "; ".join(action_plan.planned_actions)),
            (
                "authority",
                "opt-in macOS evidence only; delivery landing remains sandbox-authoritative",
            ),
        ],
        subtitle="Trusted candidate code will run in a managed worktree.",
    )
    answer = input("Start this explicit host-local verification? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        print("No host-local resources were started.")
        raise SystemExit(1)


def _run_local_delivery_verification(
    project_dir: Path,
    action_plan: LocalActionPlan,
    keep_on_failure: bool,
):
    """Run the exact candidate that the operator approved, without landing authority."""
    from harness.local_runner import (
        LocalRunnabilityRunner,
        LocalRunnerOptions,
        LocalVerificationRequest as RunnerLocalVerificationRequest,
    )
    from harness.local_runner_candidate import LocalCandidateRequest

    if (
        action_plan.workspace_root is None
        or action_plan.target_root is None
        or action_plan.candidate is None
    ):
        raise ValueError("local action plan is incomplete")
    candidate = action_plan.candidate
    mirror = Path(getattr(candidate, "mirror_path"))
    build_id = str(getattr(candidate, "build_id"))
    browser_helper = (
        Path(project_dir)
        / ".echelon"
        / "runtime"
        / "scripts"
        / "user-runnability-browser.mjs"
    )
    if not browser_helper.is_file():
        browser_helper = (
            Path(__file__).resolve().parents[2]
            / "runtime"
            / "scripts"
            / "user-runnability-browser.mjs"
        )
    request = RunnerLocalVerificationRequest(
        workspace_root=action_plan.workspace_root,
        target_root=action_plan.target_root,
        spec_id=action_plan.spec_id,
        target_id=action_plan.target_id,
        candidate_request=LocalCandidateRequest(
            workspace_root=action_plan.workspace_root,
            target_root=action_plan.target_root,
            spec_id=action_plan.spec_id,
            target_id=action_plan.target_id,
            build_id=build_id,
        ),
        local_run_root=mirror.parent / build_id / "local-runs",
    )
    runner = LocalRunnabilityRunner(
        candidate_resolver=lambda _request: candidate,
        browser_helper=browser_helper,
        recovery_workspace_root=action_plan.workspace_root,
    )
    return runner.verify(
        request,
        LocalRunnerOptions(
            engine=action_plan.engine,
            action_confirmed=True,
            keep_on_failure=keep_on_failure,
        ),
    )


def _print_local_verification_result(result: object) -> None:
    from echelon.cli import _banner

    status = str(getattr(result, "status", "failed"))
    fields = [
        ("status", status),
        ("local run", str(getattr(result, "local_run_id", "-"))),
        (
            "cleanup",
            "complete"
            if getattr(result, "cleanup_complete", False)
            else "recovery required",
        ),
    ]
    attestation = getattr(result, "attestation_path", None)
    if attestation is not None:
        fields.append(("local evidence", str(attestation)))
    summary = str(getattr(result, "summary", "")).strip()
    if summary:
        fields.append(("summary", summary))
    if not getattr(result, "cleanup_complete", False):
        fields.append(
            (
                "recovery",
                "echelon delivery cleanup-local "
                f"{getattr(result, 'local_run_id', '<local-run-id>')}",
            )
        )
    _banner(
        "LOCAL DELIVERY VERIFICATION",
        fields,
        subtitle=(
            "Separate local evidence; it never changes delivery landing authority."
        ),
    )


def verify_local(project_root: Path, request: LocalVerificationRequest) -> None:
    if request.keep_on_failure and request.assume_yes:
        raise ValueError("--keep-on-failure cannot be combined with --yes")
    if sys.platform != "darwin":
        raise ValueError("local verification is supported on macOS only")
    try:
        action_plan = _build_local_action_plan(
            project_root,
            request.spec_id,
            request.target_id,
            request.engine,
        )
        if not request.assume_yes:
            _confirm_local_action_plan(action_plan)
        result = _run_local_delivery_verification(
            project_root,
            action_plan,
            request.keep_on_failure,
        )
    except (OSError, RuntimeError) as exc:
        raise ValueError(str(exc)) from exc
    _print_local_verification_result(result)
    if str(getattr(result, "status", "")) != "passed":
        raise SystemExit(1)


def cleanup_local(project_root: Path, *, local_run_id: str) -> None:
    from harness.local_runner import LocalRunnabilityRunner

    root = _local_delivery_workspace_root(project_root)
    try:
        result = LocalRunnabilityRunner(recovery_workspace_root=root).cleanup(
            local_run_id
        )
    except (OSError, RuntimeError) as exc:
        raise ValueError(str(exc)) from exc
    _print_local_verification_result(result)
    if str(result.status) != "cleanup_complete":
        raise SystemExit(1)


def _find_harness_checkpoint_state(
    project_root: Path,
    spec_id: str,
) -> dict | None:
    from echelon.cli import _iter_harness_build_states

    for state in _iter_harness_build_states(project_root):
        if str(state.get("spec_id") or "") != spec_id:
            continue
        return state
    return None


def list_checkpoints(
    project_root: Path,
    *,
    spec_id: str,
    extra_args: Sequence[str] = (),
) -> None:
    from echelon.cli import _require_provider_capability

    _require_provider_capability(
        "echelon delivery checkpoint",
        ProviderCapability.BUILD,
        project_dir=project_root,
    )
    state = _find_harness_checkpoint_state(project_root, spec_id)
    if state is None:
        print(
            f"No delivery checkpoint state found for {spec_id!r}.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"CHECKPOINTS - delivery {spec_id}\n")
    rows: list[tuple[str, str, str, str, str]] = []
    checkpoints = state.get("checkpoint_commits")
    if isinstance(checkpoints, list):
        for checkpoint in checkpoints:
            if not isinstance(checkpoint, dict):
                continue
            commit = str(checkpoint.get("commit") or "").strip()
            if not commit:
                continue
            phase = str(checkpoint.get("phase") or "").strip() or "-"
            phase_group = str(checkpoint.get("phase_group") or "").strip()
            task_ids = checkpoint.get("task_ids")
            tasks = (
                ",".join(str(item) for item in task_ids)
                if isinstance(task_ids, list)
                else "-"
            )
            label = phase_group or phase
            rows.append(
                (commit[:7], "checkpoint", phase, tasks or "-", label or "-")
            )

    for key, kind in (("salvage_commit", "salvage"), ("target_commit", "target")):
        commit = str(state.get(key) or "").strip()
        if commit:
            rows.append(
                (
                    commit[:7],
                    kind,
                    "-",
                    "-",
                    str(
                        state.get("target_branch")
                        or state.get("salvage_branch")
                        or "-"
                    ),
                )
            )

    if not rows:
        print("(none)")
        return

    print("COMMIT   KIND        PHASE      TASKS                 CONTEXT")
    for commit, kind, phase, tasks, context in rows:
        print(f"{commit:<8} {kind:<11} {phase:<10} {tasks:<21} {context}")

def _option_pairs(**values: object) -> list[str]:
    pairs: list[str] = []
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, bool):
            pairs.append(f"{key}={'true' if value else 'false'}")
        else:
            pairs.append(f"{key}={value}")
    return pairs


def _run_args(request: DeliveryRunRequest) -> list[str]:
    args = [request.spec_id, *request.extra_args]
    args.extend(
        _option_pairs(
            mode=request.mode,
            max_outer=request.max_outer,
            max_inner=request.max_inner,
            token_budget=request.token_budget,
            auto_merge=request.auto_merge,
        )
    )
    if request.reset:
        args.append("--reset")
    return args


def _display_run_args(request: DeliveryRunRequest) -> list[str]:
    args = [request.spec_id, *request.extra_args]
    if request.mode is not None:
        args.append(f"--mode={request.mode}")
    if request.max_outer is not None:
        args.append(f"--max-outer={request.max_outer}")
    if request.max_inner is not None:
        args.append(f"--max-inner={request.max_inner}")
    if request.token_budget is not None:
        args.append(f"--token-budget={request.token_budget}")
    if request.auto_merge is not None:
        args.append("--auto-merge" if request.auto_merge else "--no-auto-merge")
    if request.reset:
        args.append("--reset")
    return args


def _recovery_args(request: DeliveryRecoveryRequest) -> list[str]:
    args = [request.spec_id]
    if request.answer is not None:
        args.append(request.answer)
    args.extend(request.extra_args)
    args.extend(_option_pairs(mode=request.mode))
    return args


def run_delivery(project_root: Path, request: DeliveryRunRequest) -> None:
    _run_delivery(
        project_root,
        _run_args(request),
        command_prefix="echelon delivery run",
        display_args=_display_run_args(request),
    )


def resume_delivery(project_root: Path, request: DeliveryRecoveryRequest) -> None:
    _run_delivery_resume(project_root, _recovery_args(request))


def continue_delivery(
    project_root: Path,
    request: DeliveryRecoveryRequest,
) -> None:
    if request.answer is not None:
        raise ValueError("delivery continue does not accept an answer")
    _run_delivery_continue(project_root, _recovery_args(request))


def _delivery_provisioning_blockers(
    project_root: Path,
    target_root: Path,
) -> list[str]:
    """Return target-local verification provisioning blockers without side effects."""
    from echelon.cli import _load_stack_definitions_for_project
    from echelon.stack_selection import StackSelectionError
    from harness.config import get_full_resolved_config
    from harness.stacks import provisioning_statuses, resolve_stacks

    project_root = project_root.resolve()
    target_root = target_root.resolve()
    target_config_dir = target_root / ".echelon"
    # A configured source owns its stack selection. Targets without their own
    # config keep the historical workspace-root selection for compatibility.
    target_has_source_config = target_root != project_root and any(
        (target_config_dir / name).is_file() for name in ("config.yml", "local.yml")
    )
    stack_config_root = target_root if target_has_source_config else project_root
    resolved_config = get_full_resolved_config(stack_config_root)
    stacks = resolved_config.get("stacks") or {}
    if not isinstance(stacks, Mapping):
        raise StackSelectionError("stacks must be a mapping")
    selected = stacks.get("selected") or []
    target_archetypes = stacks.get("target_archetypes") or []
    if not isinstance(selected, list) or not all(
        isinstance(stack_id, str) and stack_id.strip() for stack_id in selected
    ):
        raise StackSelectionError(
            "stacks.selected must be a list of non-empty stack IDs"
        )
    if not isinstance(target_archetypes, list) or not all(
        isinstance(archetype, str) and archetype.strip()
        for archetype in target_archetypes
    ):
        raise StackSelectionError(
            "stacks.target_archetypes must be a list of non-empty archetype IDs"
        )
    if not selected:
        return []

    definitions = _load_stack_definitions_for_project(project_root)
    resolved = resolve_stacks(
        selected,
        definitions,
        target_archetypes=set(target_archetypes) or None,
    )
    target = target_root
    blockers: list[str] = []
    for status in provisioning_statuses(resolved, target, os.environ):
        provisioner = next(
            item.provisioner
            for item in resolved.provisioners
            if item.owner_stack_id == status.owner_stack_id
            and item.provisioner.id == status.provisioner_id
        )
        environment = ", ".join(provisioner.required_environment)
        if status.state == "missing":
            blockers.append(
                "STACK_PROVISIONING_MISSING: verification provisioner "
                f"{status.provisioner_id!r} for stack {status.owner_stack_id!r} "
                "is not configured for this target. Run: "
                f"echelon stack provision --target {target}"
            )
        elif status.state == "prepared":
            blockers.append(
                "STACK_PROVISIONING_PREPARED: verification provisioner "
                f"{status.provisioner_id!r} for stack {status.owner_stack_id!r} "
                "has target-local artifacts, but Echelon did not start the service. "
                "Start the prepared service manually or configure an external URL via "
                f"{environment}."
            )
    return blockers


def _refresh_workspace_runtime_for_delivery(project_root: Path) -> None:
    """Deploy the installed Echelon-owned bundle before a delivery reads it.

    ``.echelon/runtime`` and ``.echelon/prosaic`` are generated, ignored
    workspace state.  Delivery must not silently run an older managed bundle
    after the CLI has been upgraded, because that can remove new stack-owned
    verification requirements from the resolved contract.
    """
    from echelon.prosaic_packages import (
        ProsaicBundleInstallError,
        install_prosaic_bundle,
    )

    try:
        install_prosaic_bundle(project_root)
    except ProsaicBundleInstallError as exc:
        print(
            "✗ Could not refresh Echelon's managed runtime before delivery.\n"
            f"  Workspace: {project_root}\n"
            f"  Error: {exc}\n"
            "  Fix: rerun the Echelon installer, then retry this delivery command.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def _resolve_delivery_stack_contract(project_root: Path, target_root: Path):
    """Resolve the current installed stack contract for one delivery target."""
    from harness.verification_stack_runtime import resolve_verification_stacks

    project_root = project_root.resolve()
    target_root = target_root.resolve()
    _refresh_workspace_runtime_for_delivery(project_root)
    return resolve_verification_stacks(project_root, target_root)


def _resolve_delivery_verification_services(
    config: object,
    *,
    project_root: Path,
    target_root: Path,
) -> None:
    """Attach target-applicable sandbox services from the stack contract."""
    resolved = _resolve_delivery_stack_contract(project_root, target_root)
    config.verification_services = list(resolved.services)
    config.resolved_stacks = resolved
    config.resolved_runnability = resolved.runnability


def _block_if_delivery_provisioning_incomplete(
    *,
    project_root: Path,
    target_root: Path,
) -> None:
    blockers = _delivery_provisioning_blockers(project_root, target_root)
    if not blockers:
        return
    print(
        "✗ Delivery verification provisioning is not ready for this target.\n"
        + "".join(f"  - {blocker}\n" for blocker in blockers),
        file=sys.stderr,
        end="",
    )
    raise SystemExit(1)


def _fsync_directory(path: Path) -> None:
    """Persist directory-entry changes needed by the delivery safety boundary."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_delivery_preparation_state(
    state_path: Path,
    payload: Mapping[str, object],
) -> None:
    """Atomically write Phase B evidence and persist every new directory entry."""
    from harness.lexicon_gate_io import write_json_atomic

    write_json_atomic(state_path, payload)
    _fsync_directory(state_path.parent)
    _fsync_directory(state_path.parent.parent)
    _fsync_directory(state_path.parent.parent.parent)


def _validate_locked_target_child_contract(
    *,
    project_root: Path,
    spec_dir: Path,
) -> None:
    """Fail closed when an orchestrated child's inherited target is stale."""
    target_env = os.environ.get("ECHELON_TARGET_REPO_PATH")
    if not target_env:
        return

    from harness.spec_frontmatter import read_canonical_target_entries

    expected_target_text = os.environ.get("ECHELON_TARGET_CONTRACT_JSON", "")
    expected_targets_text = os.environ.get("ECHELON_TARGETS_CONTRACT_JSON", "")
    try:
        expected_target = json.loads(expected_target_text)
        expected_targets = json.loads(expected_targets_text)
    except json.JSONDecodeError:
        expected_target = None
        expected_targets = None
    if not isinstance(expected_target, dict) or not isinstance(expected_targets, list):
        print(
            "✗ Target-child delivery is missing its inherited canonical target contract.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    canonical_targets = [
        dict(entry)
        for entry in read_canonical_target_entries(spec_dir)
    ]
    if canonical_targets != expected_targets or expected_target not in canonical_targets:
        print(
            "✗ Target-child delivery contract is stale; the canonical spec targets "
            "changed after dispatch. Restart delivery from the workspace root.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    implementation_target = os.environ.get("ECHELON_IMPLEMENTATION_TARGET", "")
    if implementation_target != str(expected_target.get("path") or ""):
        print(
            "✗ Target-child delivery metadata no longer matches the canonical target set.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    expected_path = (
        project_root
        if implementation_target == "."
        else project_root / implementation_target
    ).resolve()
    inherited_path = Path(target_env).resolve()
    source_root = Path(os.environ.get("ECHELON_SOURCE_ROOT") or target_env).resolve()
    if inherited_path != expected_path or source_root != expected_path:
        print(
            "✗ Target-child repository path no longer matches the canonical target contract.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def _prepare_delivery_build_state(
    *,
    project_root: Path,
    harness_base_dir: Path,
    spec_id: str,
    spec_dir: Path,
) -> str:
    """Create durable Phase B evidence under the per-spec mutation lease."""
    from harness.paths import build_dir, make_build_id
    from echelon.spec_lifecycle import (
        PhaseAExecutionLock,
        SpecLifecycleLocked,
        SpecMutationLock,
    )

    operation_id = f"delivery-{os.getpid()}"
    try:
        with SpecMutationLock.acquire(project_root, spec_id, operation_id):
            with PhaseAExecutionLock.acquire(project_root, operation_id):
                _validate_locked_target_child_contract(
                    project_root=project_root,
                    spec_dir=spec_dir,
                )
                _block_if_harness_phase_a_not_ready(spec_dir, spec_id)
                build_id = make_build_id()
                _write_delivery_preparation_state(
                    build_dir(harness_base_dir, build_id) / "state.json",
                    {
                        "schema_version": 1,
                        "spec_id": spec_id,
                        "build_id": build_id,
                        "status": "preparing",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                return build_id
    except SpecLifecycleLocked as exc:
        print(
            "✗ Cannot prepare delivery while the spec mutation lease is owned by "
            f"{exc.operation_id}.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def _run_delivery(
    project_root: Path,
    args: list[str],
    *,
    command_prefix: str = "echelon delivery run",
    display_args: list[str] | None = None,
) -> None:
    import logging

    from echelon.cli import (
        _banner,
        _command_display,
        _project_echelon_config,
        _require_provider_capability,
        _workspace_git_preflight,
    )

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args:
        print(f"{command_prefix}: missing spec_id\n", file=sys.stderr)
        sys.exit(1)

    rerun_command = _command_display(command_prefix, display_args or args)
    _require_provider_capability(
        command_prefix, ProviderCapability.BUILD, project_dir=project_root,
    )
    _workspace_git_preflight(project_root, command_name=rerun_command)

    spec_id = args[0]
    kv: dict[str, str] = {}
    free_text: list[str] = []
    reset = "--reset" in args[1:]
    for arg in args[1:]:
        if arg == "--reset":
            continue
        if "=" in arg and arg.partition("=")[0].strip() in {
            "mode",
            "target",
            "target_source",
            "max_outer",
            "max_inner",
            "token_budget",
            "auto_merge",
        }:
            k, _, v = arg.partition("=")
            kv[k.strip()] = v.strip()
        else:
            free_text.append(arg)
    mode = kv.get("mode", "semi")
    explicit_target = kv.get("target") or kv.get("target_source")
    if explicit_target:
        print(
            f"✗ {command_prefix} no longer accepts a target override.\n"
            "  Delivery consumes the implementation targets declared when Phase A began.\n"
            "  Start a new spec with: echelon spec run <description> "
            "--target <source-path> [--target <source-path> ...]",
            file=sys.stderr,
        )
        raise SystemExit(2)

    parts = [f"spec {spec_id}", f"{mode} mode"]
    if kv.get("max_outer"):
        parts.append(f"max {kv['max_outer']} outer iterations")
    if kv.get("max_inner"):
        parts.append(f"max {kv['max_inner']} inner iterations")
    if kv.get("token_budget"):
        parts.append(f"token_budget={kv['token_budget']}")
    auto_merge = kv.get("auto_merge")
    if auto_merge is not None:
        if auto_merge.lower() in {"0", "false", "no", "off"}:
            parts.append("no_auto_merge")
        else:
            parts.append("auto_merge")
    if free_text:
        parts.append(f"task: {' '.join(free_text)}")
    if reset:
        parts.append("--reset")
    user_message = " ".join(parts)

    # Orchestrator mode: spec targets take priority over local echelon-config.yml.
    # Check targets first so a polyrepo root with its own echelon-config.yml (e.g. for
    # deploy) doesn't silently bypass target validation and run against the wrong repo.
    from harness.spec_frontmatter import (
        find_spec_dir,
        read_targets,
        write_status as _write_spec_status,
    )
    from harness.spec_snapshot import snapshot_spec_dir
    from echelon.orchestrator import (
        run_multi_target,
        validate_single_target,
        validate_targets,
    )

    target_env = os.environ.get("ECHELON_TARGET_REPO_PATH")
    polyrepo_env = os.environ.get("ECHELON_POLYREPO_ROOT")
    target_name_env = os.environ.get("ECHELON_TARGET_REPO_NAME")
    direct_target_path: Path | None = None
    spec_search_root = Path(polyrepo_env).resolve() if polyrepo_env else project_root
    harness_base_dir = project_root
    config_root = project_root
    if target_env and polyrepo_env:
        config_root = Path(polyrepo_env).resolve()
        harness_base_dir = (
            config_root
            / "runs"
            / "targets"
            / (target_name_env or Path(target_env).resolve().name)
        )
        _sync_polyrepo_runtime_extension(config_root, harness_base_dir)
    spec_dir = find_spec_dir(spec_id, spec_search_root)
    if spec_dir is not None:
        resolved_spec_id = spec_dir.name
        polyrepo_root = spec_dir.parent.parent
        try:
            snapshot_spec_dir(spec_dir, polyrepo_root)
        except OSError as e:
            print(
                "✗ Could not preserve spec artifacts before harness run.\n"
                f"  Error: {e}\n"
                "  Refusing to continue because untracked spec work could be lost.",
                file=sys.stderr,
            )
            sys.exit(1)
        targets_rel: list[str] = read_targets(spec_dir)
        if targets_rel and not target_env:
            _block_if_spec_task_targets_mismatch(
                spec_dir,
                targets_rel,
                resolved_spec_id,
            )
            if len(targets_rel) == 1:
                workspace_target = _resolve_harness_workspace_target(
                    polyrepo_root,
                    targets_rel[0],
                    spec_dir=spec_dir,
                    spec_id=resolved_spec_id,
                    rerun_command=rerun_command,
                )
                target_rel = (
                    "."
                    if workspace_target.source_root == workspace_target.workspace_root
                    else workspace_target.source_root.relative_to(workspace_target.workspace_root).as_posix()
                )
                if target_rel != targets_rel[0]:
                    print(
                        "✗ Declared implementation target is not a canonical workspace source path.\n"
                        f"  declared: {targets_rel[0]}\n"
                        f"  resolved: {target_rel}\n"
                        "  Delivery will not rewrite Phase A target metadata; regenerate the spec "
                        "with the resolved --target path.",
                        file=sys.stderr,
                    )
                    raise SystemExit(2)
                if workspace_target.source_root == workspace_target.workspace_root:
                    direct_target_path = workspace_target.source_root
                else:
                    target = validate_single_target([target_rel], polyrepo_root)
                    sys.exit(run_multi_target(
                        spec_id,
                        [target],
                        args[1:],
                        **_workspace_target_dispatch_metadata(workspace_target),
                    ))

            else:
                # A spec may declare multiple targets. run_multi_target assigns
                # canonical task ownership and serializes cross-target dependency
                # order so shared progress writes cannot race.
                targets = validate_targets(targets_rel, polyrepo_root)
                _block_if_harness_phase_a_not_ready(spec_dir, resolved_spec_id)
                source_ids: dict[str, str] = {}
                source_git_roles: dict[str, str] = {}
                for target in targets:
                    target_metadata = _source_dispatch_metadata(
                        target=target,
                        polyrepo_root=polyrepo_root,
                        source_id=None,
                    )
                    source_ids.update(target_metadata["source_ids"])
                    source_git_roles.update(target_metadata["source_git_roles"])
                dispatch_metadata: dict[str, object] = {
                    "workspace_root": polyrepo_root.resolve(),
                    "workspace_git_role": "orchestration",
                    "source_ids": source_ids,
                    "source_git_roles": source_git_roles,
                }
                sys.exit(run_multi_target(spec_id, targets, args[1:], **dispatch_metadata))

        if not target_env and direct_target_path is None:
            _print_missing_spec_target_error(spec_id, command_prefix=command_prefix)
            sys.exit(1)

    if not target_env and direct_target_path is None:
        _print_missing_spec_target_error(spec_id, command_prefix=command_prefix)
        sys.exit(1)

    # Validate authored build inputs before Phase A readiness.  A malformed
    # published task/plan needs its migration guidance, while a well-formed but
    # incomplete spec needs the Phase A recovery guidance.  Both checks happen
    # before creating Git or sandbox resources.
    from harness.skills.run_skill import _count_tasks
    from harness.plan_validation import PlanValidationError, validate_plan_file
    from harness.task_validation import TaskValidationError

    try:
        task_count = _count_tasks(spec_id, str(spec_search_root))
    except TaskValidationError as e:
        tasks_path = (
            spec_dir / "tasks.md"
            if spec_dir is not None
            else Path("specs") / spec_id / "tasks.md"
        )
        print(
            "✗ tasks.md is not in canonical format.\n"
            f"  Error: {e}\n"
            f"  Preview migration: python -m harness migrate-tasks {tasks_path}\n"
            f"  Apply migration:   python -m harness migrate-tasks {tasks_path} --write\n"
            f"  Then rerun:        {rerun_command}",
            file=sys.stderr,
        )
        sys.exit(1)
    if spec_dir is not None and (spec_dir / "plan.md").exists():
        try:
            validate_plan_file(spec_dir / "plan.md")
        except PlanValidationError as e:
            plan_path = spec_dir / "plan.md"
            print(
                "✗ plan.md is not in canonical format.\n"
                f"  Error: {e}\n"
                f"  Preview migration: python -m harness migrate-plan {plan_path}\n"
                f"  Apply migration:   python -m harness migrate-plan {plan_path} --write\n"
                f"  Then rerun:        {rerun_command}",
                file=sys.stderr,
            )
            sys.exit(1)
    if spec_dir is not None:
        _block_if_harness_phase_a_not_ready(spec_dir, spec_dir.name)

    from harness.config import load_config, ValidationError as HarnessValidationError
    from harness.docker_provider import DockerWorktreeProvider
    from harness.gitops import GitOpsManager
    from harness.skills.run_skill import run

    # Single-repo mode: require local Echelon harness config.
    echelon_yml = _project_echelon_config(config_root)
    if not echelon_yml.exists():
        print(
            "✗ Harness not initialised for this project.\n"
            f"  Expected: {echelon_yml}\n"
            "  Fix: run 'echelon delivery init' first, or add 'targets:' to your spec.",
            file=sys.stderr,
        )
        sys.exit(1)

    from harness.paths import mirror_path as _mirror_path_fn
    mirror_path = _mirror_path_fn(harness_base_dir)
    if not mirror_path.exists() and not target_env:
        print(
            "✗ Harness mirror not initialised for this project.\n"
            f"  Expected: {mirror_path}\n"
            "  Fix: run 'echelon delivery init' to create the mirror.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        config = load_config(project_root=config_root, squad_only=bool(target_env))
    except HarnessValidationError as e:
        _print_harness_config_error(e)
        sys.exit(1)
    if not hasattr(config, "verification") or not hasattr(
        config.verification, "execution"
    ):
        from harness.config import VerificationConfig

        config.verification = VerificationConfig()
    if direct_target_path is not None:
        config.target_repo = str(direct_target_path.resolve())
        if not getattr(config, "target_default_branch", None):
            config.target_default_branch = "main"
        if getattr(config, "provider", None) not in {"docker", "e2b", "modal", "daytona"}:
            config.provider = "docker"
        _apply_target_verify_command_detection(
            config,
            target_repo=direct_target_path.resolve(),
            spec_id=spec_id,
        )
    elif target_env:
        target_repo_path = Path(target_env).resolve()
        config.target_repo = str(target_repo_path)
        if not getattr(config, "target_default_branch", None):
            config.target_default_branch = "main"
        if getattr(config, "provider", None) not in {"docker", "e2b", "modal", "daytona"}:
            config.provider = "docker"
        _apply_target_verify_command_detection(
            config,
            target_repo=target_repo_path,
            spec_id=spec_id,
        )
    _resolve_delivery_verification_services(
        config,
        project_root=config_root,
        target_root=Path(config.target_repo),
    )
    if config.verification.execution == "host":
        _block_if_delivery_provisioning_incomplete(
            project_root=config_root,
            target_root=Path(config.target_repo),
        )
    gitops = GitOpsManager(config, base_dir=str(harness_base_dir))
    if target_env and not mirror_path.exists():
        gitops.clone_mirror(config.target_repo)
    provider = DockerWorktreeProvider(
        buffer_limit_bytes=config.buffer_limit_bytes,
        container_cli=_container_runtime_cli(config),
    )

    assert spec_dir is not None
    delivery_build_id = _prepare_delivery_build_state(
        project_root=spec_dir.parent.parent,
        harness_base_dir=harness_base_dir,
        spec_id=spec_dir.name,
        spec_dir=spec_dir,
    )

    target_display = str(getattr(config, "target_repo", None) or "local")
    _banner("HARNESS RUN", [
        ("Spec", f"{spec_id}" + (f"  ({task_count} tasks)" if task_count else "")),
        ("Mode", mode),
        ("Target", target_display),
    ])

    if spec_dir is not None:
        _write_spec_status(spec_dir, "in_progress")

    try:
        outcome = run(
            user_message,
            provider,
            gitops,
            base_dir=str(harness_base_dir),
            config=config,
            resume_build_id=delivery_build_id,
            orchestration_root=spec_search_root,
            summary_command=command_prefix,
        )
        # A child target process is the authority for its own delivery outcome.
        # Multi-target orchestration must never infer success from rendered text.
        if _delivery_outcome_exit_code(outcome):
            raise SystemExit(1)
    except Exception as exc:
        if _is_docker_unavailable_error(exc):
            _mark_current_harness_state_blocked(
                harness_base_dir,
                spec_id,
                "docker_unavailable",
            )
            print(
                f"✗ {_container_runtime_display(config)} is not running or is unreachable.\n"
                f"  Error: {exc}\n"
                f"  Fix: {_container_runtime_fix(_container_runtime_cli(config))}, then rerun:\n"
                f"       {rerun_command}",
                file=sys.stderr,
            )
            sys.exit(1)
        _print_harness_error_and_exit(
            project_root=harness_base_dir,
            spec_id=spec_id,
            command=rerun_command,
            exc=exc,
        )


def _delivery_outcome_exit_code(outcome: object) -> int:
    """Return a process outcome from typed delivery state, never rendered text."""
    from harness.delivery_results import DeliveryRunOutcome

    if not isinstance(outcome, DeliveryRunOutcome):
        # Keeps CLI adapters compatible with legacy/mocked run adapters. The
        # production run skill always returns a typed DeliveryRunOutcome.
        return 0
    if outcome.landing.status == "blocked":
        return 1
    return 0 if any(result.status == "converged" for result in outcome.results) else 1


def _block_if_harness_phase_a_not_ready(spec_dir: Path, spec_id: str) -> None:
    """Fail before build LLM dispatch when published Phase A inputs are invalid."""
    readiness = validate_phase_a_readiness({"status": "done"}, [spec_dir])
    if readiness.ready:
        return

    blockers = "\n".join(f"  - {blocker}" for blocker in readiness.blockers)
    print(
        "✗ Phase A build inputs are not ready.\n"
        f"  Spec dir: {spec_dir}\n"
        "  Blockers:\n"
        f"{blockers}\n"
        "  Fix: run 'echelon spec continue' to republish Phase A artifacts, then rerun:\n"
        f"       echelon delivery run {spec_id}",
        file=sys.stderr,
    )
    sys.exit(1)


def _is_docker_unavailable_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        ("docker" in message or "podman" in message)
        and (
            "daemon is running" in message
            or "docker api" in message
            or "docker.sock" in message
            or "podman.sock" in message
            or "cannot connect to the docker daemon" in message
            or "failed to connect" in message
            or "connection refused" in message
        )
    )


def _container_runtime_fix(container_cli: str) -> str:
    if container_cli == "podman":
        return "start the Podman machine (`podman machine start`) and wait until it reports running"
    return "start Docker Desktop and wait until it reports running"


def _container_runtime_cli(config: object) -> str:
    cli = getattr(config, "container_cli", "docker")
    if cli not in {"docker", "podman"}:
        return "docker"
    return cli


def _container_runtime_display(config: object) -> str:
    cli = _container_runtime_cli(config)
    return "Docker" if cli == "docker" else "Podman"


def _mark_current_harness_state_blocked(
    project_root: Path,
    spec_id: str,
    reason: str,
    error: str = "",
) -> None:
    try:
        from harness.paths import build_dir, current_build_marker, runs_dir
        from harness.state import DELIVERY_STATE_VERSION, StateStore

        marker = current_build_marker(project_root, spec_id)
        if marker.exists():
            state_dir = build_dir(project_root, marker.read_text().strip()) / "state"
        else:
            state_dir = runs_dir(project_root) / "state"
        state_store = StateStore(state_dir, spec_id)
        data = state_store.read()
        if not data:
            return
        status = data.get("status")
        if status in {"converged", "failed", "cancelled_by_coordinator"}:
            return
        if data.get("delivery_state_version") == DELIVERY_STATE_VERSION:
            if status == "blocked":
                phase = data.get("blocked_phase")
            elif status == "running":
                phase = "implementation"
            elif status == "validating":
                phase = "visual"
            elif status == "reviewing":
                phase = "review"
            elif status == "finalizing":
                phase = "finalization"
            elif status == "verified":
                phases = data.get("enabled_phases")
                completed = data.get("last_completed_phase")
                phase = "finalization"
                if isinstance(phases, list) and completed in phases:
                    index = phases.index(completed)
                    if index + 1 < len(phases):
                        phase = phases[index + 1]
            else:
                phase = "implementation"
            if phase not in {"implementation", "visual", "review", "finalization"}:
                phase = "implementation"
            updates = {"blocked_phase": phase, "termination_reason": reason}
            if error:
                updates["harness_error"] = error
            state_store.transition("blocked", updates=updates)
            return

        # Legacy state remains V1. The coordinator is the only component that
        # can select and snapshot its V2 phase plan from the active config.
        data["status"] = "blocked"
        data["termination_reason"] = reason
        if error:
            data["harness_error"] = error
        state_store.write(data)
    except Exception:
        pass


def _print_harness_error_and_exit(
    *,
    project_root: Path,
    spec_id: str,
    command: str,
    exc: Exception,
) -> None:
    _mark_current_harness_state_blocked(
        project_root,
        spec_id,
        "harness_error",
        str(exc),
    )
    print(
        "✗ Harness run failed before completion.\n"
        f"  Error: {exc}\n"
        "  State was marked blocked instead of left running.\n"
        f"  Next:  {command if spec_id in command else f'{command} {spec_id}'}",
        file=sys.stderr,
    )
    sys.exit(1)


def _refresh_harness_state_spec_paths(
    *,
    project_root: Path,
    spec_id: str,
    state: dict,
    state_store: object,
) -> tuple[dict, Path | None, bool]:
    """Refresh persisted harness artifact paths from the current project.

    Older or failed runs can retain stale paths in state. Resume must not trust
    those paths when the project has a resolvable current spec directory.
    """
    from harness.spec_frontmatter import find_spec_dir

    spec_dir = find_spec_dir(spec_id, project_root)
    if spec_dir is None:
        return state, None, False

    updates = {
        "spec_dir": str(spec_dir),
        "spec_file": str(spec_dir / "spec.md"),
        "tasks_file": str(spec_dir / "tasks.md"),
    }
    refreshed = dict(state)
    changed = any(str(refreshed.get(key) or "") != value for key, value in updates.items())
    if not changed:
        return state, spec_dir, False

    refreshed.update(updates)
    state_store.write(refreshed)  # type: ignore[attr-defined]
    return refreshed, spec_dir, True


def _harness_error_resume_blockers(*, project_root: Path, spec_id: str, spec_dir: Path | None) -> list[str]:
    """Return blockers that make a previous harness_error unsafe to retry."""
    if spec_dir is None:
        return [f"no spec directory found for {spec_id!r}"]

    blockers: list[str] = []
    from harness.task_validation import TaskValidationError, count_tasks_for_spec

    try:
        task_count = count_tasks_for_spec(spec_id, project_root)
    except TaskValidationError as exc:
        task_count = 0
        blockers.append(f"tasks.md is not canonical: {exc}")
    if task_count <= 0 and not any("tasks.md" in blocker for blocker in blockers):
        blockers.append("tasks.md has no canonical task rows")

    readiness = validate_phase_a_readiness({"status": "done"}, [spec_dir])
    if not readiness.ready:
        blockers.extend(readiness.blockers or ["Phase A build inputs are not ready"])
    return blockers


def _is_docs_report_only_containment_violation(state: dict) -> bool:
    """Return True for legacy containment blocks caused only by docs reports."""
    if state.get("termination_reason") != "containment_violation":
        return False

    violation = state.get("containment_violation")
    if not isinstance(violation, dict):
        return False

    changed_status = violation.get("changed_status")
    if not isinstance(changed_status, list) or not changed_status:
        return False

    return all(
        _is_allowed_external_documentation_status(str(line))
        for line in changed_status
    )


def _is_allowed_external_documentation_status(status_line: str) -> bool:
    path = _status_path(status_line)
    if not path.startswith("specs/"):
        return False
    return PurePosixPath(path).name in {
        "documentation-impact-report.md",
        "docs-verification-report.md",
    }


def _status_path(status_line: str) -> str:
    line = status_line.strip()
    if not line:
        return ""
    path = status_line[3:].strip() if len(status_line) >= 4 else line
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path.strip('"').replace("\\", "/")


def _is_phase_a_build_incomplete_retry(state: dict) -> bool:
    """Return True when build_incomplete should retry without git recovery."""
    if state.get("termination_reason") != "build_incomplete":
        return False
    if state.get("salvage_commit") or state.get("target_commit"):
        return False
    checkpoint_commits = state.get("checkpoint_commits")
    if isinstance(checkpoint_commits, list) and checkpoint_commits:
        return False

    build_status = str(state.get("build_status") or "").strip()
    build_reason = str(state.get("build_reason") or "")
    return (
        build_status == "phase_a_not_ready"
        or "Phase A artifacts are not build-ready" in build_reason
        or "constitution.md contains unresolved template markers" in build_reason
    )


def _parse_harness_resume_args(args: list[str]) -> tuple[str, dict[str, str], str]:
    spec_id = args[0]
    kv: dict[str, str] = {}
    answer_parts: list[str] = []
    i = 1
    while i < len(args):
        arg = args[i]
        if arg == "--mode" and i + 1 < len(args):
            kv[arg.removeprefix("--")] = args[i + 1].strip()
            i += 2
            continue
        if arg.startswith("--mode="):
            kv["mode"] = arg.partition("=")[2].strip()
        elif "=" in arg:
            key, _, value = arg.partition("=")
            key = key.strip()
            if key == "mode":
                kv[key] = value.strip()
            elif key == "answer":
                answer_parts.append(value.strip())
            else:
                answer_parts.append(arg)
        else:
            answer_parts.append(arg)
        i += 1
    return spec_id, kv, " ".join(part for part in answer_parts if part).strip()


def _run_delivery_resume(
    project_root: Path,
    args: list[str],
    *,
    command_prefix: str = "echelon delivery resume",
    display_args: list[str] | None = None,
    require_answer: bool = True,
) -> None:
    import logging

    from echelon.cli import (
        _banner,
        _command_display,
        _print_legacy_branchless_recovery_notice,
        _project_echelon_config,
        _require_provider_capability,
        _workspace_git_preflight,
        _workspace_git_present,
    )

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args or args[0] in ("-h", "--help"):
        print(
            f"Usage: {command_prefix} <spec_id> [mode=<guided|semi|banzai>] [answer]\n\n"
            "Resume or continue a blocked delivery run.\n"
            "Supports blocker_escalation, verify_command_needed,\n"
                "checkpoint continuation, repaired harness_error, docker_unavailable,\n"
                "verification-infrastructure retries,\n"
            "downstream visual/review/finalization failures, and recovery from\n"
            "build_incomplete/publish_failed committed work.\n\n"
            "Steps:\n"
            "  1. Fix the blocker shown by the previous delivery output.\n"
            "     For blocker_escalation: pass the answer to 'echelon delivery resume'.\n"
            "     For verify_command_needed: add verify_command to echelon-config.yml\n"
            "     (or re-run 'echelon delivery init' to auto-detect high-confidence commands).\n"
            "  2. Run: echelon delivery continue <spec_id> when no answer is needed.\n",
        )
        return

    rerun_command = _command_display(command_prefix, display_args or args)
    _require_provider_capability(
        command_prefix, ProviderCapability.BUILD, project_dir=project_root,
    )
    spec_id, kv, resume_answer = _parse_harness_resume_args(args)
    mode = kv.get("mode", "semi")
    target_resume_command = "resume" if require_answer else "continue"

    from harness.config import load_config, ValidationError as HarnessValidationError
    from harness.docker_provider import DockerWorktreeProvider
    from harness.gitops import GitOpsManager
    from harness.paths import build_dir, current_build_marker, runs_dir
    from harness.spec_frontmatter import find_spec_dir, read_targets
    from harness.state import StateStore

    target_env = os.environ.get("ECHELON_TARGET_REPO_PATH")
    polyrepo_env = os.environ.get("ECHELON_POLYREPO_ROOT")
    target_name_env = os.environ.get("ECHELON_TARGET_REPO_NAME")
    direct_target_path: Path | None = None
    cwd = project_root
    spec_search_root = Path(polyrepo_env).resolve() if polyrepo_env else cwd
    harness_base_dir = cwd
    config_root = cwd
    if target_env and polyrepo_env:
        config_root = Path(polyrepo_env).resolve()
        harness_base_dir = (
            config_root
            / "runs"
            / "targets"
            / (target_name_env or Path(target_env).resolve().name)
        )
        _sync_polyrepo_runtime_extension(config_root, harness_base_dir)

    spec_dir = find_spec_dir(spec_id, spec_search_root)
    if spec_dir is not None and not target_env:
        from echelon.orchestrator import (
            run_multi_target,
            validate_single_target,
            validate_targets,
        )

        resolved_spec_id = spec_dir.name
        polyrepo_root = spec_dir.parent.parent
        targets_rel: list[str] = read_targets(spec_dir)
        if targets_rel:
            _block_if_spec_task_targets_mismatch(
                spec_dir,
                targets_rel,
                resolved_spec_id,
            )
            if len(targets_rel) == 1:
                workspace_target = _resolve_harness_workspace_target(
                    polyrepo_root,
                    targets_rel[0],
                    spec_dir=spec_dir,
                    spec_id=resolved_spec_id,
                    rerun_command=rerun_command,
                )
                target_rel = (
                    "."
                    if workspace_target.source_root == workspace_target.workspace_root
                    else workspace_target.source_root.relative_to(
                        workspace_target.workspace_root
                    ).as_posix()
                )
                if workspace_target.source_root == workspace_target.workspace_root:
                    direct_target_path = workspace_target.source_root
                else:
                    target = validate_single_target([target_rel], polyrepo_root)
                    sys.exit(
                        run_multi_target(
                            spec_id,
                            [target],
                            args[1:],
                            command=target_resume_command,
                            **_workspace_target_dispatch_metadata(workspace_target),
                        )
                    )

            else:
                targets = validate_targets(targets_rel, polyrepo_root)
                source_ids: dict[str, str] = {}
                source_git_roles: dict[str, str] = {}
                for target in targets:
                    target_metadata = _source_dispatch_metadata(
                        target=target,
                        polyrepo_root=polyrepo_root,
                        source_id=None,
                    )
                    source_ids.update(target_metadata["source_ids"])
                    source_git_roles.update(target_metadata["source_git_roles"])
                    sys.exit(
                        run_multi_target(
                            spec_id,
                            targets,
                            args[1:],
                            workspace_root=polyrepo_root.resolve(),
                            workspace_git_role="orchestration",
                            source_ids=source_ids,
                            source_git_roles=source_git_roles,
                            command=target_resume_command,
                        )
                    )

            if direct_target_path is None:
                _print_missing_spec_target_error(spec_id, command_prefix=command_prefix)
                sys.exit(1)

    if not target_env and direct_target_path is None:
        _print_missing_spec_target_error(spec_id, command_prefix=command_prefix)
        sys.exit(1)

    echelon_yml = _project_echelon_config(config_root)
    if not echelon_yml.exists():
        print(
            "✗ Harness not initialised for this project.\n"
            f"  Expected: {echelon_yml}\n"
            "  Fix: run 'echelon delivery init' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        config = load_config(project_root=config_root, squad_only=bool(target_env))
    except HarnessValidationError as e:
        _print_harness_config_error(e)
        sys.exit(1)
    if not hasattr(config, "verification") or not hasattr(
        config.verification, "execution"
    ):
        from harness.config import VerificationConfig

        config.verification = VerificationConfig()
    if direct_target_path is not None:
        config.target_repo = str(direct_target_path.resolve())
        if not getattr(config, "target_default_branch", None):
            config.target_default_branch = "main"
        if getattr(config, "provider", None) not in {"docker", "e2b", "modal", "daytona"}:
            config.provider = "docker"
        _apply_target_verify_command_detection(
            config,
            target_repo=direct_target_path.resolve(),
            spec_id=spec_id,
        )
    elif target_env:
        target_repo_path = Path(target_env).resolve()
        config.target_repo = str(target_repo_path)
        if not getattr(config, "target_default_branch", None):
            config.target_default_branch = "main"
        if getattr(config, "provider", None) not in {"docker", "e2b", "modal", "daytona"}:
            config.provider = "docker"
        _apply_target_verify_command_detection(
            config,
            target_repo=target_repo_path,
            spec_id=spec_id,
        )

    _resolve_delivery_verification_services(
        config,
        project_root=config_root,
        target_root=Path(config.target_repo),
    )
    if config.verification.execution == "host":
        _block_if_delivery_provisioning_incomplete(
            project_root=config_root,
            target_root=Path(config.target_repo),
        )

    # Resolve state_dir from the current-build marker; fall back to runs/state/
    # for runs that pre-date build_id or were started without one.
    marker = current_build_marker(harness_base_dir, spec_id)
    build_id = marker.read_text().strip() if marker.exists() else ""
    if marker.exists():
        state_dir = build_dir(harness_base_dir, build_id) / "state"
    else:
        state_dir = runs_dir(harness_base_dir) / "state"
    state_store = StateStore(state_dir, spec_id)
    state = state_store.read()
    if not _workspace_git_present(cwd):
        if state:
            _print_legacy_branchless_recovery_notice(
                rerun_command
            )
        else:
            _workspace_git_preflight(
                cwd,
                command_name=rerun_command,
            )

    if not state:
        print(
            f"✗ No harness state found for spec {spec_id!r}.\n"
            "  Run 'echelon delivery run <spec_id>' to start a new run.",
            file=sys.stderr,
        )
        sys.exit(1)

    state, resolved_spec_dir, spec_paths_refreshed = _refresh_harness_state_spec_paths(
        project_root=spec_search_root,
        spec_id=spec_id,
        state=state,
        state_store=state_store,
    )

    current_status = state.get("status", "unknown")
    termination_reason = state.get("termination_reason", "")
    if (
        state.get("build_status") == "provider_session_limit"
        and termination_reason in {"build_incomplete", "publish_failed"}
    ):
        state["termination_reason"] = "provider_session_limit"
        state_store.write(state)
        termination_reason = "provider_session_limit"
    recoverable_reasons = {"build_incomplete", "publish_failed"}
    continuation_reasons = {
        "blocker_escalation",
        "delivery_prompt_invalid",
        "checkpoint_outer_cap",
        "docker_unavailable",
        "convergence_stalled",
        "no_progress",
            "provider_session_limit",
            "target_merge_failed",
            # This may be a repaired harness classifier or a repaired sandbox
            # prerequisite. Retrying preserves the checkpoint and lets the
            # current verifier acquire fresh evidence; it does not accept the
            # old infrastructure failure as success.
            "verification_infrastructure",
            "sandbox_verification_unavailable",
        }
    downstream_continuation_reasons = {
        "visual": {
            "app_runtime_failed",
            "missing_registered_worktree",
            "verified_provenance_mismatch",
            "visual_failed",
            "visual_feedback_failed",
        },
        "review": {
            "missing_pr_url",
            "review_boundary_failed",
            "review_provider_failed",
            "review_reentry_checkpoint_failed",
            "review_side_effects_pending",
            "review_staging_failed",
        },
        "finalization": {
            "finalization_write_failed",
            "lifecycle_status_conflict",
            "target_merge_failed",
            "verified_provenance_mismatch",
        },
    }
    blocked_phase = str(state.get("blocked_phase") or "")
    if termination_reason in downstream_continuation_reasons.get(
        blocked_phase, set()
    ):
        continuation_reasons.add(termination_reason)
    if _is_docs_report_only_containment_violation(state):
        continuation_reasons.add("containment_violation")
    retryable_error_reasons = {"harness_error"}

    resumable_statuses = {
        "blocked",
        "running",
        "interrupted",
        "verified",
        "validating",
        "reviewing",
        "finalizing",
    }
    if (
        current_status not in resumable_statuses
        and termination_reason not in recoverable_reasons
    ):
        print(
            f"✗ Spec {spec_id!r} has no resumable delivery checkpoint "
            f"(status={current_status!r}).\n"
            "  Use 'echelon delivery run <spec_id>' to start a new run.",
            file=sys.stderr,
        )
        sys.exit(1)

    if current_status == "blocked" and termination_reason not in {
        "verify_command_needed",
        *recoverable_reasons,
        *continuation_reasons,
        *retryable_error_reasons,
    }:
        if termination_reason == "outer_cap":
            next_command, next_explanation = _outer_cap_delivery_action(
                spec_id, state.get("max_outer")
            )
            print(
                f"✗ Spec {spec_id!r} exhausted its outer-loop budget and cannot be resumed in place.\n"
                f"  Next: {next_command}\n"
                f"  {next_explanation}\n"
                "  Destructive alternative: "
                f"echelon delivery run {spec_id} --reset discards the blocked delivery checkpoints.",
                file=sys.stderr,
            )
            sys.exit(1)
        if termination_reason == "build_blocked":
            build_reason = str(state.get("build_reason") or "the build agent reported a blocker")
            print(
                f"✗ Spec {spec_id!r} is blocked by the build agent.\n"
                f"  Blocker: {build_reason}\n"
                "  Resolve the blocker; do not retry delivery until it is resolved.\n"
                f"  For a spec decision: echelon spec reopen {spec_id}\n"
                f"  Then start a new delivery run: echelon delivery run {spec_id}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(
            f"✗ Spec {spec_id!r} is blocked for unsupported resume reason: {termination_reason!r}.\n"
            f"  This is delivery state, not spec-planning state.\n"
            f"  State file: {state_store.state_file}\n"
            f"  After fixing the blocker, retry: echelon delivery resume {spec_id}\n"
            f"  To discard this blocked delivery state and start fresh: echelon delivery run {spec_id} --reset",
            file=sys.stderr,
        )
        sys.exit(1)

    gitops = GitOpsManager(config, base_dir=str(harness_base_dir))
    escalation_file = state.get("escalation_file")
    if resume_answer and escalation_file:
        from harness.escalation import EscalationHandler

        EscalationHandler(str(build_dir(harness_base_dir, build_id))).resume(
            str(escalation_file),
            resume_answer,
        )
    elif require_answer and escalation_file:
        print(
            f"✗ Spec {spec_id!r} is waiting for a delivery answer.\n"
            f"  Escalation file: {escalation_file}\n"
            f"  Answer with: echelon delivery resume {spec_id} \"<answer>\"\n"
            f"  If no answer is needed, continue with: echelon delivery continue {spec_id}",
            file=sys.stderr,
        )
        sys.exit(1)
    elif require_answer and not resume_answer:
        print(
            "delivery resume without an answer is deprecated; "
            f"use echelon delivery continue {spec_id} when no answer is needed.",
            file=sys.stderr,
        )

    if _is_phase_a_build_incomplete_retry(state):
        blockers = _harness_error_resume_blockers(
            project_root=spec_search_root,
            spec_id=spec_id,
            spec_dir=resolved_spec_dir,
        )
        if blockers:
            print(
                f"✗ Spec {spec_id!r} is still blocked after Phase A repair.\n"
                "  Resume preflight failed:\n"
                + "".join(f"  - {blocker}\n" for blocker in blockers)
                + f"  Fix the blockers, then re-run: echelon delivery resume {spec_id}",
                file=sys.stderr,
            )
            sys.exit(1)

        fields = [
            ("Spec", spec_id),
            ("Reason", "phase_a_repaired"),
        ]
        if resolved_spec_dir is not None:
            fields.append(("Spec dir", str(resolved_spec_dir)))
        if spec_paths_refreshed:
            fields.append(("State", "refreshed stale spec artifact paths"))
        _banner("HARNESS RESUME — RETRYING", fields)

        from harness.skills.run_skill import run
        provider = DockerWorktreeProvider(
            buffer_limit_bytes=config.buffer_limit_bytes,
            container_cli=_container_runtime_cli(config),
        )
        user_message = f"spec {spec_id} mode={mode} resume"
        try:
            outcome = run(
                user_message,
                provider,
                gitops,
                base_dir=str(harness_base_dir),
                config=config,
                resume_build_id=build_id or None,
                orchestration_root=spec_search_root,
                summary_command=command_prefix,
            )
            if _delivery_outcome_exit_code(outcome):
                raise SystemExit(1)
        except Exception as exc:
            if _is_docker_unavailable_error(exc):
                _mark_current_harness_state_blocked(
                    harness_base_dir,
                    spec_id,
                    "docker_unavailable",
                )
                print(
                    f"✗ {_container_runtime_display(config)} is not running or is unreachable.\n"
                    f"  Error: {exc}\n"
                    f"  Fix: {_container_runtime_fix(_container_runtime_cli(config))}, then rerun:\n"
                    f"       echelon delivery continue {spec_id}",
                    file=sys.stderr,
                )
                sys.exit(1)
            _print_harness_error_and_exit(
                project_root=harness_base_dir,
                spec_id=spec_id,
                command=rerun_command,
                exc=exc,
            )
        _exit_if_provider_session_limited(state_store)
        return

    if termination_reason in retryable_error_reasons:
        blockers = _harness_error_resume_blockers(
            project_root=spec_search_root,
            spec_id=spec_id,
            spec_dir=resolved_spec_dir,
        )
        if blockers:
            print(
                f"✗ Spec {spec_id!r} is still blocked after the previous harness error.\n"
                "  Resume preflight failed:\n"
                + "".join(f"  - {blocker}\n" for blocker in blockers)
                + f"  Fix the blockers, then re-run: echelon delivery resume {spec_id}",
                file=sys.stderr,
            )
            sys.exit(1)

        fields = [
            ("Spec", spec_id),
            ("Reason", termination_reason),
        ]
        if resolved_spec_dir is not None:
            fields.append(("Spec dir", str(resolved_spec_dir)))
        if spec_paths_refreshed:
            fields.append(("State", "refreshed stale spec artifact paths"))
        _banner("HARNESS RESUME — RETRYING", fields)

        from harness.skills.run_skill import run
        provider = DockerWorktreeProvider(
            buffer_limit_bytes=config.buffer_limit_bytes,
            container_cli=_container_runtime_cli(config),
        )
        user_message = f"spec {spec_id} mode={mode} resume"
        try:
            outcome = run(
                user_message,
                provider,
                gitops,
                base_dir=str(harness_base_dir),
                config=config,
                resume_build_id=build_id or None,
                orchestration_root=spec_search_root,
                summary_command=command_prefix,
            )
            if _delivery_outcome_exit_code(outcome):
                raise SystemExit(1)
        except Exception as exc:
            if _is_docker_unavailable_error(exc):
                _mark_current_harness_state_blocked(
                    harness_base_dir,
                    spec_id,
                    "docker_unavailable",
                )
                print(
                    f"✗ {_container_runtime_display(config)} is not running or is unreachable.\n"
                    f"  Error: {exc}\n"
                    f"  Fix: {_container_runtime_fix(_container_runtime_cli(config))}, then rerun:\n"
                    f"       echelon delivery continue {spec_id}",
                    file=sys.stderr,
                )
                sys.exit(1)
            _print_harness_error_and_exit(
                project_root=harness_base_dir,
                spec_id=spec_id,
                command=rerun_command,
                exc=exc,
            )
        _exit_if_provider_session_limited(state_store)
        return

    if termination_reason in recoverable_reasons:
        from harness.recovery import HarnessRecoveryError, recover_blocked_run

        recovery_project_dir = Path(
            str(
                state.get("target_repo_path")
                or state.get("target_path")
                or state.get("source_root")
                or config.target_repo
                or harness_base_dir
            )
        )
        if not recovery_project_dir.is_absolute():
            recovery_project_dir = (config_root / recovery_project_dir).resolve()

        try:
            recovered = recover_blocked_run(
                project_dir=recovery_project_dir,
                spec_id=spec_id,
                state=state,
                gitops=gitops,
                build_id=build_id,
            )
        except HarnessRecoveryError as e:
            print(
                f"✗ Harness recovery failed for spec {spec_id!r}: {e}",
                file=sys.stderr,
            )
            sys.exit(1)

        action = "applied" if recovered.applied else "already present"
        fields = [
            ("Spec", spec_id),
            ("Reason", termination_reason),
            ("Source", recovered.source),
            ("Commit", recovered.commit[:12]),
            ("Branch", recovered.target_branch),
            ("Status", action),
        ]
        if recovered.backed_up_untracked:
            fields.append(("Untracked backups", str(len(recovered.backed_up_untracked))))
            fields.append(("Backup dir", recovered.backup_dir))
        _banner("HARNESS RESUME — RECOVERED", fields)

        from harness.skills.run_skill import run
        provider = DockerWorktreeProvider(
            buffer_limit_bytes=config.buffer_limit_bytes,
            container_cli=_container_runtime_cli(config),
        )
        user_message = f"spec {spec_id} mode={mode} resume"
        try:
            outcome = run(
                user_message,
                provider,
                gitops,
                base_dir=str(harness_base_dir),
                config=config,
                resume_build_id=build_id or None,
                orchestration_root=spec_search_root,
                summary_command=command_prefix,
            )
            if _delivery_outcome_exit_code(outcome):
                raise SystemExit(1)
        except Exception as exc:
            if _is_docker_unavailable_error(exc):
                _mark_current_harness_state_blocked(
                    harness_base_dir,
                    spec_id,
                    "docker_unavailable",
                )
                print(
                    f"✗ {_container_runtime_display(config)} is not running or is unreachable.\n"
                    f"  Error: {exc}\n"
                    f"  Fix: {_container_runtime_fix(_container_runtime_cli(config))}, then rerun:\n"
                    f"       echelon delivery continue {spec_id}",
                    file=sys.stderr,
                )
                sys.exit(1)
            _print_harness_error_and_exit(
                project_root=harness_base_dir,
                spec_id=spec_id,
                command=rerun_command,
                exc=exc,
            )
        _exit_if_provider_session_limited(state_store)
        return

    if not config.verify_command:
        print(
            _format_missing_verify_command_resume_message(echelon_yml, spec_id),
            file=sys.stderr,
        )
        sys.exit(1)

    _banner("HARNESS RESUME", [
        ("Spec", spec_id),
        ("Verify", config.verify_command),
    ])

    from harness.skills.run_skill import run
    provider = DockerWorktreeProvider(
        buffer_limit_bytes=config.buffer_limit_bytes,
        container_cli=_container_runtime_cli(config),
    )
    user_message = f"spec {spec_id} mode={mode} resume"
    try:
        outcome = run(
            user_message,
            provider,
            gitops,
            base_dir=str(harness_base_dir),
            config=config,
            resume_build_id=build_id or None,
            orchestration_root=spec_search_root,
            summary_command=command_prefix,
        )
        if _delivery_outcome_exit_code(outcome):
            raise SystemExit(1)
    except Exception as exc:
        if _is_docker_unavailable_error(exc):
            _mark_current_harness_state_blocked(
                harness_base_dir,
                spec_id,
                "docker_unavailable",
            )
            print(
                f"✗ {_container_runtime_display(config)} is not running or is unreachable.\n"
                f"  Error: {exc}\n"
                f"  Fix: {_container_runtime_fix(_container_runtime_cli(config))}, then rerun:\n"
                f"       echelon delivery continue {spec_id}",
                file=sys.stderr,
            )
            sys.exit(1)
        _print_harness_error_and_exit(
            project_root=harness_base_dir,
            spec_id=spec_id,
            command=rerun_command,
            exc=exc,
        )
    _exit_if_provider_session_limited(state_store)


def _run_delivery_continue(
    project_root: Path,
    args: list[str],
    *,
    command_prefix: str = "echelon delivery continue",
    display_args: list[str] | None = None,
) -> None:
    _run_delivery_resume(
        project_root,
        args,
        command_prefix=command_prefix,
        display_args=display_args,
        require_answer=False,
    )


def _exit_if_provider_session_limited(state_store: object) -> None:
    """Return a nonzero target status for a resumable provider-exhaustion block."""
    read = getattr(state_store, "read", None)
    state = read() if callable(read) else {}
    if (
        isinstance(state, dict)
        and state.get("status") == "blocked"
        and state.get("termination_reason") == "provider_session_limit"
        and state.get("build_status") == "provider_session_limit"
    ):
        raise SystemExit(2)
