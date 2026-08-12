"""Best-effort narrative summaries for terminal Echelon lifecycle handoffs."""
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Mapping, Sequence

from harness.prosaic_prompt_loader import ProsaicPromptLoader


MAX_EVIDENCE_BYTES = 12 * 1024
_MAX_TEXT = 600
_MAX_ITEMS = 16
_MAX_LINE = 280
_MAX_TOTAL_LINES = 1_600
_MAX_FALLBACK_LINE = _MAX_TOTAL_LINES // 8
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_ANSI_RE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[ -/]*[0-~])"
)


def _clean_text(value: object, *, limit: int = _MAX_TEXT) -> str:
    text = str(value or "").strip()
    text = _ANSI_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"
    return text


def _clean_opaque_text(value: object, *, limit: int = _MAX_TEXT) -> str:
    """Bound one opaque fact without normalizing its internal shell syntax."""
    text = str(value or "").strip()
    text = _ANSI_RE.sub("", text)
    text = re.sub(r"[\r\n]+", " ", text)
    text = _CONTROL_RE.sub("", text)
    if len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"
    return text


def _clean_items(value: object, *, limit: int = _MAX_ITEMS) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    cleaned = tuple(_clean_text(item, limit=180) for item in value)
    return tuple(item for item in cleaned if item)[:limit]

@dataclass(frozen=True)
class WorkedOnEvidence:
    command: str
    status: str
    run_id: str = ""
    spec_id: str = ""
    goal: str = ""
    current_phase: str = ""
    completed_phases: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    completed_tasks: tuple[str, ...] = ()
    task_titles: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    duration: str = ""
    outcomes: tuple[str, ...] = ()
    commits: tuple[str, ...] = ()
    verification: str = ""
    verification_failures: tuple[str, ...] = ()
    blocker: str = ""
    provider_limit_message: str = ""
    next_command: str = ""
    next_note: str = ""
    targets: tuple[str, ...] = ()
    strategies: tuple[str, ...] = ()

    def to_json(self) -> str:
        """Serialize a normalized packet without exceeding the prompt budget."""
        raw = asdict(self)
        normalized: dict[str, object] = {}
        for key, value in raw.items():
            if isinstance(value, tuple):
                normalized[key] = list(_clean_items(value))
            else:
                limit = 360 if key in {
                    "verification",
                    "blocker",
                    "provider_limit_message",
                    "next_command",
                    "next_note",
                } else _MAX_TEXT
                cleaner = (
                    _clean_opaque_text
                    if key in {"verification", "next_command"}
                    else _clean_text
                )
                normalized[key] = cleaner(value, limit=limit)
        encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) <= MAX_EVIDENCE_BYTES:
            return encoded

        optional = (
            "artifacts",
            "task_titles",
            "decisions",
            "completed_phases",
            "completed_tasks",
            "targets",
            "strategies",
        )
        for key in optional:
            values = normalized.get(key)
            if not isinstance(values, list):
                continue
            while values and len(encoded.encode("utf-8")) > MAX_EVIDENCE_BYTES:
                values.pop()
                encoded = json.dumps(
                    normalized,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
        if len(encoded.encode("utf-8")) > MAX_EVIDENCE_BYTES:
            for key in ("run_id", "spec_id", "goal", "current_phase"):
                normalized[key] = _clean_text(normalized.get(key), limit=160)
            encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        for key in ("verification_failures", "commits", "outcomes"):
            values = normalized.get(key)
            if not isinstance(values, list):
                continue
            while len(values) > 1 and len(encoded.encode("utf-8")) > MAX_EVIDENCE_BYTES:
                values.pop()
                encoded = json.dumps(
                    normalized,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
        for key in ("verification_failures", "commits", "outcomes"):
            values = normalized.get(key)
            if not isinstance(values, list):
                continue
            while values and len(encoded.encode("utf-8")) > MAX_EVIDENCE_BYTES:
                values.pop()
                encoded = json.dumps(
                    normalized,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
        if len(encoded.encode("utf-8")) > MAX_EVIDENCE_BYTES:
            normalized["blocker"] = _clean_text(normalized.get("blocker"), limit=240)
            normalized["provider_limit_message"] = _clean_text(
                normalized.get("provider_limit_message"), limit=240
            )
            normalized["verification"] = _clean_opaque_text(
                normalized.get("verification"), limit=240
            )
            normalized["next_command"] = _clean_opaque_text(
                normalized.get("next_command"), limit=240
            )
            normalized["next_note"] = _clean_text(
                normalized.get("next_note"), limit=240
            )
            encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_EVIDENCE_BYTES:
            for key in (
                "command",
                "status",
                "run_id",
                "spec_id",
                "goal",
                "current_phase",
                "duration",
            ):
                normalized[key] = _clean_text(normalized.get(key), limit=80)
            encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        return encoded


def _format_elapsed(started: object, finished: object) -> str:
    start_text = _clean_text(started)
    finish_text = _clean_text(finished)
    if not start_text or not finish_text:
        return ""
    try:
        start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(finish_text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    seconds = max(0, int((finish - start).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _recorded_duration(source: Mapping[str, object]) -> str:
    recorded = _clean_text(
        source.get("duration") or source.get("elapsed") or source.get("elapsed_time")
    )
    if recorded:
        return recorded
    return _format_elapsed(
        source.get("started_at") or source.get("created_at"),
        source.get("finished_at")
        or source.get("completed_at")
        or source.get("updated_at"),
    )


def _attributed_commits(source: Mapping[str, object]) -> tuple[str, ...]:
    commits: list[str] = []
    for key in ("lifecycle_commits", "commit_records", "checkpoint_commits"):
        records = source.get(key)
        if not isinstance(records, (list, tuple)):
            continue
        for record in records:
            if not isinstance(record, Mapping):
                continue
            sha = _clean_text(record.get("commit") or record.get("sha"), limit=64)
            subject = _clean_text(record.get("subject"), limit=150)
            if not sha or not subject or re.fullmatch(r"[0-9a-fA-F]{7,64}", sha) is None:
                continue
            commits.append(f"{sha[:12]} — {subject}")
    return tuple(dict.fromkeys(commits))[:_MAX_ITEMS]


def _recorded_verification(source: Mapping[str, object]) -> str:
    summary = _clean_opaque_text(
        source.get("verification_summary") or source.get("verification")
    )
    if summary:
        return summary
    raw = source.get("last_verify_result")
    if not isinstance(raw, Mapping) or "passed" not in raw:
        return ""
    status = "passed" if bool(raw.get("passed")) else "failed"
    try:
        duration = float(raw.get("duration_s") or 0)
    except (TypeError, ValueError):
        duration = 0
    return f"{status} in {duration:.1f}s" if duration else status


def phase_a_evidence(
    *,
    command: str,
    state: Mapping[str, object],
    result: object | None,
    next_command: str,
    next_note: str = "",
) -> WorkedOnEvidence:
    status = _clean_text(getattr(result, "status", "") or state.get("status") or "unknown")
    decisions = state.get("decisions") or state.get("decision_log") or ()
    artifacts = state.get("artifacts") or ()
    return WorkedOnEvidence(
        command=_clean_text(command),
        status=status,
        run_id=_clean_text(state.get("run_id")),
        spec_id=_clean_text(state.get("spec_id")),
        goal=_clean_text(state.get("user_message") or state.get("message")),
        current_phase=_clean_text(getattr(result, "phase", "") or state.get("phase")),
        completed_phases=_clean_items(state.get("completed_phases")),
        decisions=_clean_items(decisions),
        artifacts=_clean_items(
            artifacts.keys() if isinstance(artifacts, Mapping) else artifacts
        ),
        duration=_recorded_duration(state),
        outcomes=_clean_items(state.get("outcomes")),
        commits=_attributed_commits(state),
        verification=_recorded_verification(state),
        blocker=_clean_text(
            state.get("blocked_reason")
            or state.get("termination_reason")
            or state.get("escalation_question")
        ),
        provider_limit_message=_clean_text(state.get("provider_limit_message")),
        next_command=_clean_opaque_text(next_command),
        next_note=_clean_text(
            next_note or state.get("next_note") or state.get("recovery_note")
        ),
        targets=_clean_items(state.get("implementation_targets")),
    )


def delivery_evidence(
    *,
    command: str,
    intent: object,
    result_map: Mapping[str, object],
    comparison: Mapping[str, object],
    next_command: str,
) -> WorkedOnEvidence:
    strategy_rows = comparison.get("strategies")
    strategy_rows = strategy_rows if isinstance(strategy_rows, Mapping) else {}
    results = tuple(result_map.values())
    converged = any(
        bool(row.get("converged"))
        for row in strategy_rows.values()
        if isinstance(row, Mapping)
    )
    reasons = tuple(
        _clean_text(getattr(result, "termination_reason", ""))
        for result in results
        if _clean_text(getattr(result, "termination_reason", "")) not in {"", "converged"}
    )
    statuses = tuple(_clean_text(getattr(result, "status", "")) for result in results)
    status = "done" if converged else next((item for item in statuses if item), "unknown")
    if status in {"failed", "error"} and reasons and reasons[0] in {
        "build_incomplete",
        "publish_failed",
        "checkpoint_outer_cap",
        "provider_session_limit",
        "blocker_escalation",
    }:
        status = "blocked"

    completed_tasks: list[str] = []
    for row in strategy_rows.values():
        if isinstance(row, Mapping):
            completed_tasks.extend(_clean_items(row.get("completed_task_ids")))

    converged_ids = tuple(
        str(strategy_id)
        for strategy_id, row in strategy_rows.items()
        if isinstance(row, Mapping) and bool(row.get("converged"))
    )
    selected_ids = converged_ids or tuple(
        str(strategy_id) for strategy_id in result_map
    )
    selected_ids = tuple(
        strategy_id for strategy_id in selected_ids if strategy_id in result_map
    )
    selected_results = tuple(result_map[strategy_id] for strategy_id in selected_ids)
    selected_rows = tuple(
        row
        for strategy_id in selected_ids
        if isinstance((row := strategy_rows.get(strategy_id)), Mapping)
    )

    verification = ""
    failures: list[str] = []
    observed_verification: list[bool] = []
    for result in selected_results:
        verify = getattr(result, "final_verify", None)
        if verify is None:
            continue
        passed = bool(getattr(verify, "passed", False))
        observed_verification.append(passed)
        for failure in getattr(verify, "failures", None) or ():
            failures.append(_clean_text(getattr(failure, "error", failure), limit=240))
    if observed_verification:
        verification = "passed" if all(observed_verification) else "failed"
        if len(selected_results) == 1:
            duration_s = getattr(
                getattr(selected_results[0], "final_verify", None),
                "duration_s",
                0,
            )
            if duration_s:
                verification = f"{verification} in {float(duration_s):.1f}s"

    outcomes: list[str] = []
    commits: list[str] = []
    for row in selected_rows:
        outcomes.extend(_clean_items(row.get("outcomes")))
        commits.extend(_attributed_commits(row))
    provider_limit_message = ""
    for row in selected_rows:
        provider_limit_message = _clean_text(row.get("provider_limit_message"))
        if provider_limit_message:
            break
    durations = tuple(_recorded_duration(row) for row in selected_rows)
    duration = next((item for item in durations if item), "")
    next_note = next(
        (
            _clean_text(
                row.get("next_note")
                or row.get("recovery_note")
                or row.get("recommended_action")
            )
            for row in selected_rows
            if _clean_text(
                row.get("next_note")
                or row.get("recovery_note")
                or row.get("recommended_action")
            )
        ),
        "",
    )

    strategies = getattr(intent, "strategies", ()) or tuple(strategy_rows)
    return WorkedOnEvidence(
        command=_clean_text(command),
        status=status,
        spec_id=_clean_text(getattr(intent, "spec_id", "")),
        goal=_clean_text(getattr(intent, "goal", "") or getattr(intent, "user_message", "")),
        completed_tasks=tuple(dict.fromkeys(completed_tasks))[:_MAX_ITEMS],
        duration=duration,
        outcomes=tuple(dict.fromkeys(outcomes))[:_MAX_ITEMS],
        commits=tuple(dict.fromkeys(commits))[:_MAX_ITEMS],
        verification=verification,
        verification_failures=tuple(failures)[:_MAX_ITEMS],
        blocker=reasons[0] if reasons else "",
        provider_limit_message=provider_limit_message,
        next_command=_clean_opaque_text(next_command),
        next_note=next_note,
        strategies=_clean_items(strategies),
    )

@dataclass(frozen=True)
class NarrativeCandidate:
    """One controller-authored sentence available for terminal selection."""

    id: str
    text: str
    priority: int
    required: bool = False


def _sentence(value: object, *, prefix: str = "") -> str:
    """Build one controller-owned sentence from a bounded durable fact."""
    text = _clean_text(value)
    text = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    rendered = f"{prefix}{text}" if text else prefix.rstrip()
    return rendered if rendered[-1:] in {".", "!", "?"} else f"{rendered}."


def _exact_fact_sentence(value: object, *, prefix: str) -> str:
    """Wrap an opaque durable fact without interpreting its internal syntax."""
    text = _clean_opaque_text(value)
    rendered = f"{prefix}{text}"
    return rendered if rendered[-1:] in {".", "!", "?"} else f"{rendered}."


def narrative_candidates(
    evidence: WorkedOnEvidence,
) -> tuple[NarrativeCandidate, ...]:
    """Construct the complete controller-authored terminal narrative menu."""
    unfinished = evidence.status != "done"
    goal = _clean_text(evidence.goal or evidence.spec_id) or "the requested work"
    command = _clean_text(evidence.command) or "the requested work"
    candidates: list[NarrativeCandidate] = []

    if evidence.outcomes:
        primary = _sentence(evidence.outcomes[0])
    elif unfinished:
        primary = _sentence(f"Attempted {command} for {goal}")
    else:
        primary = _sentence(f"Completed work toward {goal}")
    candidates.append(NarrativeCandidate("outcome", primary, 10))

    progress_count = len(evidence.completed_tasks) or len(evidence.completed_phases)
    if progress_count:
        progress_kind = "tasks" if evidence.completed_tasks else "phases"
        progress = _sentence(
            f"Worked through {progress_count} {progress_kind} toward {goal}"
        )
    elif evidence.duration:
        progress = _sentence(
            evidence.duration,
            prefix="The recorded run duration was ",
        )
    else:
        progress = "No completed tasks or phases were recorded."
    candidates.append(NarrativeCandidate("progress", progress, 20))

    for index, outcome in enumerate(evidence.outcomes[1:], start=2):
        candidates.append(
            NarrativeCandidate(
                f"outcome-{index}",
                _sentence(outcome),
                30 + index,
            )
        )
    for index, decision in enumerate(evidence.decisions, start=1):
        candidates.append(
            NarrativeCandidate(
                f"decision-{index}",
                _sentence(decision, prefix="Recorded decision: "),
                50 + index,
            )
        )

    if evidence.verification == "passed":
        verification = "Verification passed for the completed work."
    elif evidence.verification == "failed":
        verification = "Verification found remaining issues in the current work."
    elif evidence.verification:
        verification = _exact_fact_sentence(
            evidence.verification,
            prefix="Recorded verification: ",
        )
    else:
        verification = "No verification result was recorded."
    candidates.append(NarrativeCandidate("verification", verification, 70))

    for index, commit in enumerate(evidence.commits, start=1):
        candidates.append(
            NarrativeCandidate(
                f"commit-{index}",
                _exact_fact_sentence(
                    commit,
                    prefix="Recorded lifecycle commit ",
                ),
                80 + index,
            )
        )

    if unfinished:
        reason = _clean_text(evidence.blocker)
        blocker = (
            _sentence(reason, prefix="The run stopped because ")
            if reason
            else _sentence(
                evidence.status or "unknown",
                prefix="The recorded run status is ",
            )
        )
        candidates.append(
            NarrativeCandidate(
                "blocker",
                blocker,
                100,
                required=bool(reason),
            )
        )
        if evidence.provider_limit_message:
            candidates.append(
                NarrativeCandidate(
                    "provider-limit",
                    _exact_fact_sentence(
                        evidence.provider_limit_message,
                        prefix="The provider reported a limit: ",
                    ),
                    110,
                    required=True,
                )
            )
        if evidence.next_command:
            next_action = _exact_fact_sentence(
                f"`{_clean_opaque_text(evidence.next_command)}`",
                prefix="Next, run ",
            )
        elif evidence.next_note:
            next_action = _sentence(evidence.next_note)
        else:
            next_action = ""
        if next_action:
            candidates.append(
                NarrativeCandidate(
                    "next-action",
                    next_action,
                    120,
                    required=True,
                )
            )
    else:
        candidates.append(
            NarrativeCandidate(
                "readiness",
                "The completed work is ready for review.",
                120,
            )
        )

    return tuple(candidates)


def _selected_candidate_ids(
    raw: str,
    candidates: Sequence[NarrativeCandidate],
) -> tuple[str, ...] | None:
    """Validate the model's closed selection contract without reading prose."""
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or set(payload) != {"line_ids"}:
        return None
    ids = payload["line_ids"]
    if not isinstance(ids, list) or not 4 <= len(ids) <= 8:
        return None
    if any(not isinstance(candidate_id, str) for candidate_id in ids):
        return None
    selected = tuple(ids)
    if len(set(selected)) != len(selected):
        return None

    candidate_ids = tuple(candidate.id for candidate in candidates)
    if len(set(candidate_ids)) != len(candidate_ids):
        return None
    known = set(candidate_ids)
    if any(candidate_id not in known for candidate_id in selected):
        return None
    required = {
        candidate.id
        for candidate in candidates
        if candidate.required
    }
    if not required.issubset(selected):
        return None
    return selected


def _fallback_candidate_ids(
    candidates: Sequence[NarrativeCandidate],
) -> tuple[str, ...]:
    ordered = sorted(candidates, key=lambda candidate: (candidate.priority, candidate.id))
    selected = {
        candidate.id
        for candidate in ordered
        if candidate.required
    }
    for candidate in ordered:
        if len(selected) >= 8:
            break
        selected.add(candidate.id)
    return tuple(
        candidate.id
        for candidate in ordered
        if candidate.id in selected
    )


def _candidate_selection_packet(
    candidates: Sequence[NarrativeCandidate],
) -> tuple[str, tuple[NarrativeCandidate, ...]]:
    """Serialize a bounded candidate menu without dropping required facts."""
    retained = list(candidates)

    def encode() -> str:
        return json.dumps(
            {"candidates": [asdict(candidate) for candidate in retained]},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    packet = encode()
    while len(packet.encode("utf-8")) > MAX_EVIDENCE_BYTES:
        optional = [
            candidate
            for candidate in retained
            if not candidate.required
        ]
        if len(retained) <= 4 or not optional:
            raise ValueError("required narrative candidates exceed prompt budget")
        drop = max(optional, key=lambda candidate: (candidate.priority, candidate.id))
        retained.remove(drop)
        packet = encode()
    return packet, tuple(retained)


def fallback_summary(evidence: WorkedOnEvidence) -> tuple[str, ...]:
    """Render deterministic candidates when selection is unavailable or invalid."""
    candidates = narrative_candidates(evidence)
    selected = set(_fallback_candidate_ids(candidates))
    return tuple(
        candidate.text
        for candidate in sorted(
            candidates,
            key=lambda candidate: (candidate.priority, candidate.id),
        )
        if candidate.id in selected
    )


def generate_summary(
    project_root: Path,
    evidence: WorkedOnEvidence,
    *,
    config: object | None = None,
    provider: object | None = None,
) -> tuple[str, ...]:
    """Invoke SUMMARIZER once, then render only controller-authored candidates."""
    candidates = narrative_candidates(evidence)
    fallback = fallback_summary(evidence)
    try:
        selection_packet, dispatch_candidates = _candidate_selection_packet(candidates)
        artifact = ProsaicPromptLoader(project_root).load_agent("echelon.summarizer")
        if artifact is None:
            return fallback
        rendered = ProsaicPromptLoader.render_agent(artifact, selection_packet)
        if provider is None:
            from harness.config import load_config
            from harness.llm_provider import AICodingCliProvider

            provider = AICodingCliProvider(
                config or load_config(project_root, squad_only=True)
            )
        with tempfile.TemporaryDirectory(prefix="echelon-summary-") as workdir:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = provider.run_agent_result(
                    workdir,
                    rendered.prompt,
                    timeout_ms=30_000,
                    request_metadata={
                        "prompt_metadata": rendered.frontmatter,
                        "quiet": True,
                        "allow_non_git_cwd": True,
                    },
                )
        if int(getattr(result, "exit_code", -1)) != 0 or bool(
            getattr(result, "timed_out", False)
        ):
            return fallback
        selected_ids = _selected_candidate_ids(
            str(getattr(result, "stdout", "")),
            dispatch_candidates,
        )
        if selected_ids is None:
            return fallback
        candidate_map = {
            candidate.id: candidate.text
            for candidate in candidates
        }
        return tuple(candidate_map[candidate_id] for candidate_id in selected_ids)
    except (Exception, KeyboardInterrupt):
        return fallback


def format_worked_on(lines: Sequence[str]) -> str:
    return "\n".join(lines)


@dataclass
class _SummaryScope:
    command: str
    project_root: Path
    spec_id: str = ""
    emitted: bool = False
    initial_phase_a_signature: tuple[str, int, int] | None = None
    exit_status: str = ""
    pending_evidence: WorkedOnEvidence | None = None


_ACTIVE_SCOPE: ContextVar[_SummaryScope | None] = ContextVar(
    "echelon_worked_on_scope",
    default=None,
)


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _phase_a_scope_evidence(scope: _SummaryScope) -> WorkedOnEvidence | None:
    runs = scope.project_root / "runs"
    state_path: Path | None = None
    try:
        current = (runs / ".current").read_text(encoding="utf-8").strip()
    except OSError:
        current = ""
    if current:
        candidate = runs / current / "state.json"
        if candidate.is_file():
            state_path = candidate
    if state_path is None:
        return _phase_a_without_current_state(scope)
    signature = _phase_a_signature(scope.project_root)
    if (
        scope.command == "spec run"
        and signature is not None
        and signature == scope.initial_phase_a_signature
    ):
        return _phase_a_without_current_state(scope)
    state = _read_json_object(state_path)
    if not state:
        return _phase_a_without_current_state(scope)
    status = _clean_text(state.get("status") or "unknown")
    next_command = ""
    if status != "done":
        next_command = (
            "echelon spec resume \"<answer>\""
            if state.get("blocked_decision") or state.get("escalation_question")
            else "echelon spec continue"
        )
    return phase_a_evidence(
        command=scope.command,
        state=state,
        result=None,
        next_command=next_command,
    )


def _phase_a_without_current_state(scope: _SummaryScope) -> WorkedOnEvidence:
    failed = scope.exit_status in {"failed", "interrupted"}
    return WorkedOnEvidence(
        command=scope.command,
        status=scope.exit_status if failed else "unknown",
        spec_id=scope.spec_id,
        blocker=(
            f"{scope.command} stopped before new run state was created"
            if failed
            else ""
        ),
    )


def _delivery_scope_evidence(scope: _SummaryScope) -> WorkedOnEvidence | None:
    if not scope.spec_id:
        return None
    runs = scope.project_root / "runs"
    marker = runs / f".current-build-{scope.spec_id}"
    try:
        build_id = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return WorkedOnEvidence(
            command=scope.command,
            status=scope.exit_status or "unknown",
            spec_id=scope.spec_id,
            blocker="delivery stopped before build state was created"
            if scope.exit_status in {"failed", "interrupted"}
            else "",
            next_command=f"echelon delivery continue {scope.spec_id}"
            if scope.exit_status != "done"
            else "",
        )
    state_dir = runs / build_id / "state"
    states = [_read_json_object(path) for path in sorted(state_dir.glob("*.json"))]
    states = [state for state in states if state]
    if not states:
        return WorkedOnEvidence(
            command=scope.command,
            status=scope.exit_status or "unknown",
            spec_id=scope.spec_id,
            blocker="delivery stopped before strategy state was created"
            if scope.exit_status in {"failed", "interrupted"}
            else "",
            next_command=f"echelon delivery continue {scope.spec_id}"
            if scope.exit_status != "done"
            else "",
        )
    statuses = [
        "done" if (item := _clean_text(state.get("status"))) == "converged" else item
        for state in states
    ]
    status = "done" if statuses and all(item == "done" for item in statuses) else next(
        (item for item in statuses if item),
        "unknown",
    )
    blocker = next(
        (
            _clean_text(state.get("termination_reason") or state.get("blocked_reason"))
            for state in states
            if (
                state.get("termination_reason") or state.get("blocked_reason")
            )
            and _clean_text(
                state.get("termination_reason") or state.get("blocked_reason")
            ) != "converged"
        ),
        "",
    )
    tasks: list[str] = []
    outcomes: list[str] = []
    commits: list[str] = []
    for state in states:
        tasks.extend(_clean_items(state.get("completed_task_ids")))
        outcomes.extend(_clean_items(state.get("outcomes")))
        commits.extend(_attributed_commits(state))
    duration = next(
        (item for state in states if (item := _recorded_duration(state))),
        "",
    )
    verification = next(
        (item for state in states if (item := _recorded_verification(state))),
        "",
    )
    provider_limit_message = next(
        (
            item
            for state in states
            if (item := _clean_text(state.get("provider_limit_message")))
        ),
        "",
    )
    next_note = next(
        (
            item
            for state in states
            if (
                item := _clean_text(
                    state.get("next_note")
                    or state.get("recovery_note")
                    or state.get("recommended_action")
                )
            )
        ),
        "",
    )
    next_command = "" if status == "done" else f"echelon delivery continue {scope.spec_id}"
    return WorkedOnEvidence(
        command=scope.command,
        status=status,
        spec_id=scope.spec_id,
        completed_tasks=tuple(dict.fromkeys(tasks))[:_MAX_ITEMS],
        duration=duration,
        outcomes=tuple(dict.fromkeys(outcomes))[:_MAX_ITEMS],
        commits=tuple(dict.fromkeys(commits))[:_MAX_ITEMS],
        verification=verification,
        blocker=blocker,
        provider_limit_message=provider_limit_message,
        next_command=next_command,
        next_note=next_note,
        strategies=tuple(path.stem for path in sorted(state_dir.glob("*.json")))[:_MAX_ITEMS],
    )


def _scope_evidence(scope: _SummaryScope) -> WorkedOnEvidence | None:
    if scope.pending_evidence is not None:
        return scope.pending_evidence
    if scope.command.startswith("delivery "):
        return _delivery_scope_evidence(scope)
    return _phase_a_scope_evidence(scope)


def attach_to_terminal_fields(
    fields: Sequence[tuple[str, str]],
    evidence: WorkedOnEvidence,
    *,
    project_root: Path,
    config: object | None = None,
    provider: object | None = None,
) -> list[tuple[str, str]]:
    """Append one narrative section and satisfy an active emit-once scope."""
    if os.environ.get("ECHELON_WORKED_ON_SUMMARY") == "defer":
        _write_deferred_evidence(evidence)
        scope = _ACTIVE_SCOPE.get()
        if scope is not None:
            scope.emitted = True
        return list(fields)
    lines = generate_summary(
        project_root,
        evidence,
        config=config,
        provider=provider,
    )
    scope = _ACTIVE_SCOPE.get()
    if scope is not None:
        scope.emitted = True
    return [*fields, ("Worked on", format_worked_on(lines))]


def _write_deferred_evidence(evidence: WorkedOnEvidence) -> None:
    path = os.environ.get("ECHELON_WORKED_ON_SUMMARY_FILE", "").strip()
    if not path:
        return
    try:
        Path(path).write_text(evidence.to_json(), encoding="utf-8")
    except OSError:
        pass


def read_deferred_evidence(path: Path) -> WorkedOnEvidence | None:
    payload = _read_json_object(path)
    if not payload:
        return None
    fields = WorkedOnEvidence.__dataclass_fields__
    values: dict[str, object] = {}
    tuple_fields = {
        "completed_phases",
        "decisions",
        "completed_tasks",
        "task_titles",
        "artifacts",
        "outcomes",
        "commits",
        "verification_failures",
        "targets",
        "strategies",
    }
    for name in fields:
        value = payload.get(name, () if name in tuple_fields else "")
        values[name] = tuple(value) if isinstance(value, list) else value
    try:
        return WorkedOnEvidence(**values)
    except TypeError:
        return None


def current_worked_on_command(default: str) -> str:
    scope = _ACTIVE_SCOPE.get()
    return scope.command if scope is not None else default


def record_terminal_evidence(evidence: WorkedOnEvidence) -> None:
    scope = _ACTIVE_SCOPE.get()
    if scope is not None:
        scope.pending_evidence = evidence


def _phase_a_signature(project_root: Path) -> tuple[str, int, int] | None:
    runs = project_root / "runs"
    try:
        run_id = (runs / ".current").read_text(encoding="utf-8").strip()
        state_path = runs / run_id / "state.json"
        stat = state_path.stat()
    except OSError:
        return None
    return run_id, stat.st_mtime_ns, stat.st_size


@contextmanager
def worked_on_scope(
    command: str,
    project_root: Path,
    *,
    spec_id: str = "",
):
    """Emit exactly one summary across a possibly nested lifecycle command."""
    deferred = os.environ.get("ECHELON_WORKED_ON_SUMMARY") == "defer"
    active = _ACTIVE_SCOPE.get()
    if active is not None:
        yield active
        return

    scope = _SummaryScope(
        command=_clean_text(command),
        project_root=Path(project_root).resolve(),
        spec_id=_clean_text(spec_id),
        initial_phase_a_signature=_phase_a_signature(Path(project_root).resolve()),
    )
    token = _ACTIVE_SCOPE.set(scope)
    try:
        try:
            yield scope
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt):
                scope.exit_status = "interrupted"
            elif isinstance(exc, SystemExit) and (exc.code is None or exc.code == 0):
                scope.exit_status = "done"
            else:
                scope.exit_status = "failed"
            raise
        else:
            scope.exit_status = "done"
    finally:
        try:
            if not scope.emitted:
                evidence = _scope_evidence(scope)
                if evidence is not None:
                    if deferred:
                        _write_deferred_evidence(evidence)
                        scope.emitted = True
                    else:
                        lines = generate_summary(scope.project_root, evidence)
                        from echelon.ui import banner

                        banner(
                            "WORKED ON",
                            [("summary", format_worked_on(lines))],
                            file=sys.stderr
                            if scope.command.startswith("delivery ")
                            else None,
                        )
                        scope.emitted = True
        except (Exception, KeyboardInterrupt):
            pass
        finally:
            _ACTIVE_SCOPE.reset(token)
