"""Safe, transition-scoped provider-limit observations."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
import re


PROVIDER_LIMIT_MESSAGE_MAX = 240
PROVIDER_LIMIT_PROVENANCE_KEY = "provider_limit_provenance"
PROVIDER_LIMIT_STATE_KEYS = (
    "provider_limit_message",
    PROVIDER_LIMIT_PROVENANCE_KEY,
    "provider_reset_hint",
)

_TERMINAL_ESCAPE_RE = re.compile(
    r"(?:"
    r"\x1b\](?:(?!\x07|\x1b\\|\x9c)[\s\S])*(?:\x07|\x1b\\|\x9c|$)"
    r"|\x9d(?:(?!\x07|\x1b\\|\x9c)[\s\S])*(?:\x07|\x1b\\|\x9c|$)"
    r"|\x1b[PX^_](?:(?!\x1b\\|\x9c)[\s\S])*(?:\x1b\\|\x9c|$)"
    r"|\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x9b[0-?]*[ -/]*[@-~]"
    r"|[\x90\x98\x9e\x9f](?:(?!\x1b\\|\x9c)[\s\S])*(?:\x1b\\|\x9c|$)"
    r"|\x1b[ -/]*[0-~]"
    r")"
)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_TRANSCRIPT_CONTROL_RE = re.compile(r"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def clean_provider_transcript(value: object) -> str:
    """Strip complete terminal payloads before any transcript line search."""
    text = _TERMINAL_ESCAPE_RE.sub("", str(value or ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _TRANSCRIPT_CONTROL_RE.sub(" ", text)


def _has_unterminated_terminal_string(text: str) -> bool:
    """Return whether a stream ends inside OSC, DCS, SOS, PM, or APC framing."""
    mode = ""
    index = 0
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if not mode:
            if char == "\x1b" and following and following in "]PX^_":
                mode = "osc" if following == "]" else "st"
                index += 2
                continue
            if char == "\x9d":
                mode = "osc"
            elif char in "\x90\x98\x9e\x9f":
                mode = "st"
            index += 1
            continue
        if char == "\x9c" or (
            char == "\x1b" and following == "\\"
        ):
            mode = ""
            index += 2 if char == "\x1b" else 1
            continue
        if mode == "osc" and char == "\x07":
            mode = ""
        index += 1
    return bool(mode)


def clean_provider_transcript_streams(*values: object) -> tuple[str, ...]:
    """Sanitize independent streams without manufacturing cross-stream framing."""
    streams = tuple(str(value or "") for value in values)
    if any(_has_unterminated_terminal_string(stream) for stream in streams):
        return ()
    return tuple(clean_provider_transcript(stream) for stream in streams)


def _bounded_text(value: object, *, limit: int) -> str:
    text = clean_provider_transcript(value)
    text = _CONTROL_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"
    return text


def clean_provider_limit_message(value: object) -> str:
    """Return one safe, whitespace-normalized provider observation."""
    return _bounded_text(value, limit=PROVIDER_LIMIT_MESSAGE_MAX)


def clear_provider_limit(state: MutableMapping[str, object]) -> bool:
    """Remove every field whose meaning is tied to a provider-limit stop."""
    changed = False
    for key in PROVIDER_LIMIT_STATE_KEYS:
        if key in state:
            state.pop(key, None)
            changed = True
    return changed


def record_provider_limit(
    state: MutableMapping[str, object],
    message: object,
    *,
    phase_id: object,
    termination_reason: object,
) -> str:
    """Record a cleaned observation with the transition that owns it."""
    cleaned = clean_provider_limit_message(message)
    clear_provider_limit(state)
    phase = _bounded_text(phase_id, limit=160)
    reason = _bounded_text(termination_reason, limit=160)
    if not cleaned or not phase or not reason:
        return ""
    state["provider_limit_message"] = cleaned
    state[PROVIDER_LIMIT_PROVENANCE_KEY] = {
        "phase_id": phase,
        "termination_reason": reason,
    }
    return cleaned


def _current_reason(state: Mapping[str, object]) -> str:
    phase = _bounded_text(state.get("phase"), limit=160)
    blocked_reason = _bounded_text(state.get("blocked_reason"), limit=160)
    # Phase A terminal states own their stop through ``blocked_reason``.  A
    # delivery ``termination_reason`` may coexist after recovery and must not
    # outrank that newer controller transition.
    if phase.startswith("terminal-") and blocked_reason:
        return blocked_reason
    return _bounded_text(
        state.get("termination_reason")
        or blocked_reason
        or (
            state.get("build_status")
            if state.get("build_status") == "provider_session_limit"
            else ""
        ),
        limit=160,
    )


def _current_phase(state: Mapping[str, object]) -> str:
    blocked_phase = _bounded_text(state.get("blocked_phase"), limit=160)
    if blocked_phase:
        return blocked_phase
    dispatch = state.get("last_dispatch")
    if isinstance(dispatch, Mapping):
        phase = _bounded_text(dispatch.get("phase_id"), limit=160)
        if phase:
            return phase
    phase = _bounded_text(state.get("phase"), limit=160)
    return "" if phase.startswith("terminal-") else phase


def current_provider_limit_message(
    state: Mapping[str, object],
    *,
    phase_id: object = "",
    termination_reason: object = "",
) -> str:
    """Return the observation only when its owning transition is current."""
    message = clean_provider_limit_message(state.get("provider_limit_message"))
    provenance = state.get(PROVIDER_LIMIT_PROVENANCE_KEY)
    if not message or not isinstance(provenance, Mapping):
        return ""
    recorded_phase = _bounded_text(provenance.get("phase_id"), limit=160)
    recorded_reason = _bounded_text(
        provenance.get("termination_reason"), limit=160
    )
    expected_reason = _bounded_text(termination_reason, limit=160) or _current_reason(state)
    expected_phase = _bounded_text(phase_id, limit=160) or _current_phase(state)
    if (
        not recorded_phase
        or not recorded_reason
        or not expected_reason
        or not expected_phase
    ):
        return ""
    if recorded_reason != expected_reason:
        return ""
    if recorded_phase != expected_phase:
        return ""
    return message
