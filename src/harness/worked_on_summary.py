"""Best-effort narrative summaries for terminal Echelon lifecycle handoffs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
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

    verification = ""
    failures: list[str] = []
    for result in results:
        verify = getattr(result, "final_verify", None)
        if verify is None:
            continue
        passed = bool(getattr(verify, "passed", False))
        verification = "passed" if passed else "failed"
        for failure in getattr(verify, "failures", None) or ():
            failures.append(_clean_text(getattr(failure, "error", failure), limit=240))

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
        bullets.append(f"Made progress toward {goal}.")

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
        ):
            return None
        normalized.append(bullet)
    if sum(len(item) for item in normalized) > _MAX_TOTAL_BULLETS:
        return None

    joined = " ".join(normalized).lower()
    if evidence.verification == "passed" and re.search(r"\bverification (?:failed|did not pass)\b", joined):
        return None
    if evidence.verification == "failed" and re.search(r"\bverification passed\b", joined):
        return None
    if evidence.status == "done" and re.search(r"\b(?:run|delivery|spec) (?:failed|blocked)\b", joined):
        return None
    if evidence.status in {"blocked", "failed", "error"} and re.search(
        r"\b(?:run|delivery|spec) (?:completed successfully|converged)\b",
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
