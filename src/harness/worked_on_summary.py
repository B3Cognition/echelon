"""Best-effort narrative summaries for terminal Echelon lifecycle handoffs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
from contextvars import ContextVar
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
_MAX_BULLET = 280
_MAX_TOTAL_BULLETS = 900
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def _clean_text(value: object, *, limit: int = _MAX_TEXT) -> str:
    text = str(value or "").strip()
    text = _ANSI_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
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
    verification: str = ""
    verification_failures: tuple[str, ...] = ()
    blocker: str = ""
    next_command: str = ""
    targets: tuple[str, ...] = ()
    strategies: tuple[str, ...] = ()

    def to_json(self) -> str:
        """Serialize a normalized packet without exceeding the prompt budget."""
        raw = asdict(self)
        normalized: dict[str, object] = {}
        for key, value in raw.items():
            if isinstance(value, tuple):
                normalized[key] = list(value)
            else:
                normalized[key] = value
        encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) <= MAX_EVIDENCE_BYTES:
            return encoded

        optional = (
            "artifacts",
            "task_titles",
            "decisions",
            "completed_phases",
            "completed_tasks",
            "verification_failures",
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
            normalized["goal"] = _clean_text(normalized.get("goal"), limit=160)
            normalized["blocker"] = _clean_text(normalized.get("blocker"), limit=240)
            encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        return encoded


def phase_a_evidence(
    *,
    command: str,
    state: Mapping[str, object],
    result: object | None,
    next_command: str,
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
        blocker=_clean_text(
            state.get("blocked_reason")
            or state.get("termination_reason")
            or state.get("escalation_question")
        ),
        next_command=_clean_text(next_command),
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
    converged = any(bool(row.get("converged")) for row in strategy_rows.values() if isinstance(row, Mapping))
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

    selected_results = results
    converged_ids = tuple(
        str(strategy_id)
        for strategy_id, row in strategy_rows.items()
        if isinstance(row, Mapping) and bool(row.get("converged"))
    )
    if converged_ids:
        selected_results = tuple(
            result_map[strategy_id]
            for strategy_id in converged_ids
            if strategy_id in result_map
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

    strategies = getattr(intent, "strategies", ()) or tuple(strategy_rows)
    return WorkedOnEvidence(
        command=_clean_text(command),
        status=status,
        spec_id=_clean_text(getattr(intent, "spec_id", "")),
        goal=_clean_text(getattr(intent, "goal", "") or getattr(intent, "user_message", "")),
        completed_tasks=tuple(dict.fromkeys(completed_tasks))[:_MAX_ITEMS],
        verification=verification,
        verification_failures=tuple(failures)[:_MAX_ITEMS],
        blocker=reasons[0] if reasons else "",
        next_command=_clean_text(next_command),
        strategies=_clean_items(strategies),
    )


def fallback_summary(evidence: WorkedOnEvidence) -> tuple[str, ...]:
    """Build useful narrative prose without an LLM."""
    bullets: list[str] = []
    goal = evidence.goal or evidence.spec_id or "the requested work"
    progress_count = len(evidence.completed_tasks) or len(evidence.completed_phases)
    progress_kind = "tasks" if evidence.completed_tasks else "phases"
    if progress_count:
        bullets.append(f"Worked through {progress_count} {progress_kind} toward {goal}.")
    elif evidence.status == "done":
        bullets.append(f"Completed work toward {goal}.")
    else:
        bullets.append(f"Attempted {evidence.command or 'the requested work'} for {goal}.")

    if evidence.verification:
        if evidence.verification == "passed":
            bullets.append("Verification passed for the completed work.")
        elif evidence.verification == "failed":
            bullets.append("Verification found remaining issues in the current work.")
        else:
            bullets.append(f"Verification status is {evidence.verification}.")
    if evidence.status != "done" or evidence.blocker:
        reason = evidence.blocker or evidence.status or "an unfinished run"
        bullets.append(f"The run stopped because {reason}.")
    if evidence.next_command:
        bullets.append(f"Next, run `{evidence.next_command}`.")
    if len(bullets) < 2:
        bullets.append("The run reached its terminal handoff state.")
    return tuple(bullets[:4])


def _valid_bullets(raw: str, evidence: WorkedOnEvidence) -> tuple[str, ...] | None:
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or set(payload) != {"bullets"}:
        return None
    bullets = payload.get("bullets")
    if not isinstance(bullets, list) or not 2 <= len(bullets) <= 4:
        return None

    normalized: list[str] = []
    for raw_bullet in bullets:
        if not isinstance(raw_bullet, str):
            return None
        if _ANSI_RE.search(raw_bullet) or _CONTROL_RE.search(raw_bullet):
            return None
        bullet = raw_bullet.strip()
        if (
            not bullet
            or "\n" in bullet
            or len(bullet) > _MAX_BULLET
            or bullet.startswith(("#", "- ", "* ", "• ", "```", "|"))
            or bullet[-1:] not in {".", "!", "?"}
            or len(re.findall(r"[.!?](?:\s|$)", bullet)) != 1
        ):
            return None
        normalized.append(bullet)
    if sum(len(item) for item in normalized) > _MAX_TOTAL_BULLETS:
        return None

    joined = " ".join(normalized).lower()
    if evidence.verification == "passed" and re.search(
        r"\b(?:verification|checks?|tests?) (?:failed|did not pass|found failures?)\b",
        joined,
    ):
        return None
    if evidence.verification == "failed" and re.search(
        r"\b(?:verification|checks?|tests?) (?:passed|succeeded|were successful)\b|\ball checks succeeded\b",
        joined,
    ):
        return None
    if evidence.status == "done" and re.search(
        r"\b(?:run|delivery|spec|work) (?:failed|blocked|stopped unsuccessfully)\b",
        joined,
    ):
        return None
    if evidence.status in {"blocked", "failed", "error"} and re.search(
        r"\b(?:(?:run|delivery|spec|work) (?:completed successfully|fully completed|converged)|all work (?:completed|finished)|all checks succeeded)\b",
        joined,
    ):
        return None
    return tuple(normalized)


def generate_summary(
    project_root: Path,
    evidence: WorkedOnEvidence,
    *,
    config: object | None = None,
    provider: object | None = None,
) -> tuple[str, ...]:
    """Invoke SUMMARIZER once and fall back for every unavailable/invalid result."""
    fallback = fallback_summary(evidence)
    try:
        artifact = ProsaicPromptLoader(project_root).load_agent("echelon.summarizer")
        if artifact is None:
            return fallback
        rendered = ProsaicPromptLoader.render_agent(artifact, evidence.to_json())
        if provider is None:
            from harness.config import load_config
            from harness.llm_provider import AICodingCliProvider

            provider = AICodingCliProvider(config or load_config(project_root, squad_only=True))
        with tempfile.TemporaryDirectory(prefix="echelon-summary-") as workdir:
            result = provider.run_agent_result(
                workdir,
                rendered.prompt,
                timeout_ms=30_000,
                request_metadata={"prompt_metadata": rendered.frontmatter},
            )
        if int(getattr(result, "exit_code", -1)) != 0 or bool(getattr(result, "timed_out", False)):
            return fallback
        return _valid_bullets(str(getattr(result, "stdout", "")), evidence) or fallback
    except Exception:
        return fallback


def format_worked_on(bullets: Sequence[str]) -> str:
    return "\n".join(f"• {bullet}" for bullet in bullets)


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
    statuses = [_clean_text(state.get("status")) for state in states]
    status = "done" if statuses and all(item == "done" for item in statuses) else next(
        (item for item in statuses if item),
        "unknown",
    )
    blocker = next(
        (
            _clean_text(state.get("termination_reason") or state.get("blocked_reason"))
            for state in states
            if state.get("termination_reason") or state.get("blocked_reason")
        ),
        "",
    )
    tasks: list[str] = []
    for state in states:
        tasks.extend(_clean_items(state.get("completed_task_ids")))
    next_command = "" if status == "done" else f"echelon delivery continue {scope.spec_id}"
    return WorkedOnEvidence(
        command=scope.command,
        status=status,
        spec_id=scope.spec_id,
        completed_tasks=tuple(dict.fromkeys(tasks))[:_MAX_ITEMS],
        blocker=blocker,
        next_command=next_command,
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
        return list(fields)
    bullets = generate_summary(
        project_root,
        evidence,
        config=config,
        provider=provider,
    )
    scope = _ACTIVE_SCOPE.get()
    if scope is not None:
        scope.emitted = True
    return [*fields, ("Worked on", format_worked_on(bullets))]


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
    if os.environ.get("ECHELON_WORKED_ON_SUMMARY") == "defer":
        yield None
        return
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
                    bullets = generate_summary(scope.project_root, evidence)
                    from echelon.ui import banner

                    banner(
                        "WORKED ON",
                        [("summary", format_worked_on(bullets))],
                        file=sys.stderr
                        if scope.command.startswith("delivery ")
                        else None,
                    )
                    scope.emitted = True
        except Exception:
            pass
        finally:
            _ACTIVE_SCOPE.reset(token)
