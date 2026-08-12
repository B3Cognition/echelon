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


def _clean_items(value: object, *, limit: int = _MAX_ITEMS) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    cleaned = tuple(_clean_text(item, limit=180) for item in value)
    return tuple(item for item in cleaned if item)[:limit]


def _command_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        cleaned
        for token in value.lower().split()
        if (cleaned := token.strip("`'\"()[]{}.,;:!?"))
    )


def _contains_token_sequence(recorded: tuple[str, ...], claim: str) -> bool:
    claimed = _command_tokens(claim)
    if not claimed:
        return True
    width = len(claimed)
    return any(recorded[index:index + width] == claimed for index in range(len(recorded) - width + 1))


def _recorded_verification_commands(value: str) -> tuple[tuple[str, ...], ...]:
    text = " ".join(value.lower().split())
    commands = [_command_tokens(item) for item in re.findall(r"`([^`]+)`", text)]
    for clause in re.split(r"\s*;\s*", text):
        clause = re.sub(r"^(?:recorded )?verification:\s*", "", clause)
        match = re.fullmatch(
            r"(.+?)\s+(?:passed|failed|succeeded)(?:\s+in\s+\S+)?",
            clause,
        )
        if match:
            commands.append(_command_tokens(match.group(1)))
    return tuple(dict.fromkeys(command for command in commands if command))


def _verification_command_claims(line: str) -> tuple[str, ...]:
    semantic = " ".join(line.lower().split()).rstrip(".!?")
    semantic = re.sub(r"^recorded verification:\s*", "", semantic)
    claims = list(re.findall(r"`([^`]+)`", semantic))
    cue = re.search(
        r"\b(?:with|via|using|ran|running|command(?:\s+(?:was|is))?:?)\s+(.+)$",
        semantic,
    )
    if cue:
        claims.append(cue.group(1).strip("` "))
    leading = re.fullmatch(r"(.+?)\s+(?:passed|failed|succeeded)", semantic)
    if leading and not re.fullmatch(
        r"(?:verification|validation|all checks?|checks?|all tests?|tests?)",
        leading.group(1),
    ):
        claims.append(leading.group(1))
    return tuple(dict.fromkeys(claims))


def _provider_limit_semantics(value: str) -> frozenset[str]:
    text = " ".join(value.lower().split())
    return frozenset(
        semantic
        for semantic in ("session limit", "usage limit", "rate limit", "quota")
        if re.search(rf"\b{re.escape(semantic)}\b", text)
    )


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
                normalized[key] = _clean_text(value, limit=limit)
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
            normalized["verification"] = _clean_text(
                normalized.get("verification"), limit=240
            )
            normalized["next_command"] = _clean_text(
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
    summary = _clean_text(
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
        next_command=_clean_text(next_command),
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
    for strategy_id, result in zip(selected_ids, selected_results):
        if _clean_text(getattr(result, "termination_reason", "")) != "provider_session_limit":
            continue
        row = strategy_rows.get(strategy_id)
        if isinstance(row, Mapping):
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
        next_command=_clean_text(next_command),
        next_note=next_note,
        strategies=_clean_items(strategies),
    )


def fallback_summary(evidence: WorkedOnEvidence) -> tuple[str, ...]:
    """Build useful narrative prose without an LLM."""
    def sentence(value: str, *, prefix: str = "") -> str:
        text = _clean_text(value, limit=_MAX_FALLBACK_LINE - len(prefix) - 1)
        text = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
        rendered = f"{prefix}{text}" if text else prefix.rstrip()
        return rendered if rendered[-1:] in {".", "!", "?"} else f"{rendered}."

    def command_sentence(value: str) -> str:
        text = _clean_text(
            value,
            limit=_MAX_FALLBACK_LINE - len("Next, run ``."),
        )
        text = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
        text = text.rstrip(".!?")
        return f"Next, run `{text}`."

    goal = evidence.goal or evidence.spec_id or "the requested work"
    progress_count = len(evidence.completed_tasks) or len(evidence.completed_phases)
    progress_kind = "tasks" if evidence.completed_tasks else "phases"
    if progress_count:
        progress = f"Worked through {progress_count} {progress_kind} toward {goal}."
    elif evidence.status == "done":
        progress = f"Completed work toward {goal}."
    else:
        progress = f"Attempted {evidence.command or 'the requested work'} for {goal}."
    progress = sentence(progress)

    lines: list[str] = []
    if evidence.outcomes:
        lines.append(sentence(evidence.outcomes[0]))
    elif evidence.decisions:
        lines.append(sentence(evidence.decisions[0], prefix="Recorded decision: "))
    else:
        lines.append(progress)
    if progress_count and lines[0] != progress:
        lines.append(progress)

    important: list[str] = []
    if evidence.verification:
        if evidence.verification == "passed":
            important.append("Verification passed for the completed work.")
        elif evidence.verification == "failed":
            important.append("Verification found remaining issues in the current work.")
        else:
            important.append(sentence(evidence.verification, prefix="Recorded verification: "))
    if evidence.commits:
        important.append(sentence(evidence.commits[0], prefix="Recorded lifecycle commit "))

    tail: list[str] = []
    if evidence.status != "done" or evidence.blocker:
        reason = evidence.blocker or evidence.status or "an unfinished run"
        tail.append(sentence(reason, prefix="The run stopped because "))
    if evidence.provider_limit_message:
        tail.append(
            sentence(
                evidence.provider_limit_message,
                prefix="The provider reported a limit: ",
            )
        )
    if evidence.next_note:
        tail.append(sentence(evidence.next_note))
    if evidence.next_command:
        tail.append(command_sentence(evidence.next_command))

    lines.extend(important[: max(0, 8 - len(lines) - len(tail))])
    optional: list[str] = []
    if len(evidence.outcomes) > 1:
        optional.append(sentence(evidence.outcomes[1]))
    if evidence.duration:
        optional.append(sentence(evidence.duration, prefix="Recorded duration was "))
    for detail in optional:
        if len(lines) + len(tail) < 8:
            lines.append(detail)
    if len(lines) + len(tail) < 4:
        lines.append(
            sentence(evidence.status or "unknown", prefix="The recorded run status is ")
        )
    if len(lines) + len(tail) < 4 and not evidence.verification:
        lines.append("No verification result was recorded.")
    if len(lines) + len(tail) < 4:
        lines.append("No further recovery command was recorded.")
    lines.extend(tail[: max(0, 8 - len(lines))])
    return tuple(lines[:8])


def _valid_lines(raw: str, evidence: WorkedOnEvidence) -> tuple[str, ...] | None:
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or set(payload) != {"lines"}:
        return None
    lines = payload.get("lines")
    if not isinstance(lines, list) or not 4 <= len(lines) <= 8:
        return None

    normalized: list[str] = []
    for raw_line in lines:
        if not isinstance(raw_line, str):
            return None
        if _ANSI_RE.search(raw_line) or _CONTROL_RE.search(raw_line):
            return None
        line = raw_line.strip()
        if (
            not line
            or "\n" in line
            or len(line) > _MAX_LINE
            or line.startswith(("#", "- ", "* ", "• ", "```", "|"))
            or line[-1:] not in {".", "!", "?"}
            or len(re.findall(r"[.!?](?:\s|$)", line)) != 1
        ):
            return None
        normalized.append(line)
    if sum(len(item) for item in normalized) > _MAX_TOTAL_LINES:
        return None

    joined = " ".join(normalized).lower()
    grounded = " ".join(joined.split())
    verification = evidence.verification.lower()
    if verification.startswith("passed") and re.search(
        r"\b(?:verification|checks?|tests?) (?:failed|did not pass|found failures?)\b",
        joined,
    ):
        return None
    if verification.startswith("failed") and re.search(
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
        r"\b(?:succeeded|successful(?:ly)?|shipped|converged)\b|"
        r"\ball work (?:completed|finished)\b|\ball checks succeeded\b|\bready\b|"
        r"\b(?:integration|review|merge|release|deployment)-ready\b|"
        r"\b(?:can|may|could|will)\s+(?:(?:proceed|advance|move)\b|"
        r"be\s+(?:integrated|landed|merged|released|shipped|deployed)\b)|"
        r"\b(?:proceed|advance|move)\s+to\s+(?:code review|review|integration|"
        r"landing|merge|release|shipping|deployment)\b",
        joined,
    ):
        return None
    if verification.startswith("failed") and re.search(
        r"\b(?:verification|validation|checks?|tests?) (?:passed|succeeded|were successful)\b",
        joined,
    ):
        return None
    if evidence.status in {"blocked", "failed", "error"} and evidence.provider_limit_message:
        recorded_limit_semantics = _provider_limit_semantics(
            evidence.provider_limit_message
        )
        if not recorded_limit_semantics.intersection(_provider_limit_semantics(joined)):
            return None
    exact_verification = " ".join(evidence.verification.lower().split())
    number_pattern = r"(?<![\w.,])\d[\d,]*(?:\.\d+)?(?![\d.,])"
    recorded_numbers = set(re.findall(number_pattern, exact_verification))
    recorded_verification_tokens = _command_tokens(exact_verification)
    recorded_commands = _recorded_verification_commands(exact_verification)
    for line in normalized:
        verification_line = " ".join(line.lower().split())
        if not re.search(r"\b(?:verification|validation|checks?|tests?)\b", verification_line):
            continue
        numeric_details = re.findall(number_pattern, verification_line)
        command_claims = _verification_command_claims(verification_line)
        line_tokens = _command_tokens(verification_line)
        for executable in {command[0] for command in recorded_commands}:
            if executable not in line_tokens:
                continue
            matching_commands = tuple(
                command for command in recorded_commands if command[0] == executable
            )
            if not any(
                any(
                    line_tokens[index:index + len(command)] == command
                    for index in range(len(line_tokens) - len(command) + 1)
                )
                for command in matching_commands
            ):
                return None
        if any(detail not in recorded_numbers for detail in numeric_details) or any(
            not _contains_token_sequence(recorded_verification_tokens, claim)
            for claim in command_claims
        ):
            return None
    if (
        exact_verification
        and exact_verification not in {"passed", "failed"}
        and exact_verification not in grounded
    ):
        return None
    if evidence.commits and " ".join(evidence.commits[0].lower().split()) not in grounded:
        return None
    required_outcomes = tuple(
        " ".join(item.lower().split())
        for item in (*evidence.outcomes[:2], *evidence.decisions[:2])
        if item
    )
    if any(item not in grounded for item in required_outcomes):
        return None
    grounded_claims = tuple(
        " ".join(item.lower().split())
        for item in (*evidence.outcomes, *evidence.decisions)
        if item
    )

    def exact_fact_line(line: str) -> bool:
        normalized_line = line.rstrip(".!?")
        allowed: set[str] = set()
        for item in evidence.outcomes:
            fact = " ".join(item.lower().split()).rstrip(".!?")
            allowed.update((fact, f"recorded outcome: {fact}"))
        for item in evidence.decisions:
            fact = " ".join(item.lower().split()).rstrip(".!?")
            allowed.update((fact, f"recorded decision: {fact}"))
        if exact_verification not in {"", "passed", "failed"}:
            fact = exact_verification.rstrip(".!?")
            allowed.update((fact, f"recorded verification: {fact}"))
        if evidence.commits:
            fact = " ".join(evidence.commits[0].lower().split()).rstrip(".!?")
            allowed.update(
                (
                    fact,
                    f"recorded {fact}",
                    f"recorded lifecycle commit {fact}",
                )
            )
        if evidence.provider_limit_message:
            fact = " ".join(
                evidence.provider_limit_message.lower().split()
            ).rstrip(".!?")
            allowed.update((fact, f"the {fact}", f"the provider reported a limit: {fact}"))
        if evidence.next_command:
            command = " ".join(evidence.next_command.lower().split()).rstrip(".!?")
            allowed.update(
                (
                    f"next, run {command}",
                    f"next, run `{command}`",
                    f"retry {command}",
                    f"resume {command}",
                )
            )
        return normalized_line in allowed

    def supported_lifecycle_line(line: str) -> bool:
        if any(fact in line for fact in grounded_claims):
            return True
        if evidence.verification and re.search(
            r"\b(?:verification|validation|checks?|tests?)\b", line
        ):
            return True
        if evidence.commits and evidence.commits[0].split("—", 1)[0].strip().lower() in line:
            return True
        if evidence.provider_limit_message and re.search(
            r"\b(?:(?:session|usage|rate) limit|quota)\b", line
        ):
            return True
        if evidence.blocker and (
            " ".join(evidence.blocker.lower().split()) in line
            or re.search(r"\b(?:blocked|stopped|failed|unfinished)\b", line)
        ):
            return True
        if evidence.completed_tasks or evidence.completed_phases:
            if re.search(r"\b(?:worked|progress|tasks?|phases?|completed)\b", line):
                return True
        if evidence.next_command or evidence.next_note:
            if re.search(r"\b(?:next|retry|resume|continue|remaining)\b", line):
                return True
        if evidence.status and evidence.status.lower() in line:
            return True
        if evidence.status == "done" and re.search(
            r"\b(?:ready for (?:integration|review)|ready to (?:integrate|review)|complete(?:d)?)\b",
            line,
        ):
            return True
        return False

    next_command_tokens = _command_tokens(evidence.next_command)
    for line in normalized:
        lowered = " ".join(line.lower().split())
        lowered_tokens = _command_tokens(lowered)
        if (
            evidence.status in {"blocked", "failed", "error"}
            and next_command_tokens
            and any(
                lowered_tokens[index:index + len(next_command_tokens)]
                == next_command_tokens
                for index in range(
                    len(lowered_tokens) - len(next_command_tokens) + 1
                )
            )
            and not re.match(r"^(?:next,\s*run|retry\b|resume\b|wait\b.+\bthen\b)", lowered)
        ):
            return None
        if exact_fact_line(lowered):
            continue
        if re.search(r"[;,:]|\b(?:and|but|while|then)\b", lowered):
            return None
        if not supported_lifecycle_line(lowered):
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
        if int(getattr(result, "exit_code", -1)) != 0 or bool(getattr(result, "timed_out", False)):
            return fallback
        return _valid_lines(str(getattr(result, "stdout", "")), evidence) or fallback
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
