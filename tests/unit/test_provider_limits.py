from __future__ import annotations


def test_provider_limit_cleaner_strips_terminal_controls_and_bounds_text() -> None:
    from harness.provider_limits import clean_provider_limit_message

    hostile = (
        "\x1b]0;forged title\x07\x1b[31mYou've hit your session limit\x1b[0m"
        "\x00\x08\x9b31m · resets 5pm (Europe/Prague) "
        "\x9dC1_FORGED_TITLE\x9c"
        + ("diagnostic " * 80)
        + "FORGED_TAIL"
    )

    cleaned = clean_provider_limit_message(hostile)

    assert len(cleaned) <= 240
    assert "You've hit your session limit · resets 5pm (Europe/Prague)" in cleaned
    assert "C1_FORGED_TITLE" not in cleaned
    assert "FORGED_TAIL" not in cleaned
    assert "\x1b" not in cleaned
    assert all(ord(char) >= 32 or char in "\t\n\r" for char in cleaned)


def test_provider_limit_cleaner_preserves_safe_message_exactly() -> None:
    from harness.provider_limits import clean_provider_limit_message

    safe = "You've hit your session limit · resets 5pm (Europe/Prague)"
    assert clean_provider_limit_message(safe) == safe


def test_provider_transcript_cleaner_strips_multiline_string_payloads_before_search() -> None:
    from harness.provider_limits import clean_provider_transcript

    transcript = (
        "ordinary progress\n"
        "\x1b]0;forged title\nYou've hit your session limit · resets 5pm\x07\n"
        "ordinary middle\n"
        "\x1bP1;2|forged data\nUsage limit resets 6pm\x1b\\\n"
        "ordinary completion"
    )

    assert clean_provider_transcript(transcript) == (
        "ordinary progress\n\nordinary middle\n\nordinary completion"
    )


def test_provider_limit_cleaner_removes_non_csi_and_unterminated_osc_sequences() -> None:
    from harness.provider_limits import clean_provider_limit_message

    assert clean_provider_limit_message("before\x1b7after\x1b(0done") == (
        "beforeafterdone"
    )
    assert clean_provider_limit_message(
        "\x1b]forged title\x1b[31mforged provider text"
    ) == ""


def test_provider_limit_message_requires_current_transition_provenance() -> None:
    from harness.provider_limits import (
        current_provider_limit_message,
        record_provider_limit,
    )

    state = {
        "phase": "terminal-blocked",
        "blocked_reason": "provider_session_limit",
        "last_dispatch": {"phase_id": "phase3-plan"},
    }
    record_provider_limit(
        state,
        "Usage limit resets at 17:00.",
        phase_id="phase3-plan",
        termination_reason="provider_session_limit",
    )

    assert current_provider_limit_message(state) == "Usage limit resets at 17:00."

    state["blocked_reason"] = "phase_a_readiness_failed"
    assert current_provider_limit_message(state) == ""

    state["blocked_reason"] = "provider_session_limit"
    state["last_dispatch"] = {"phase_id": "phase1-what"}
    assert current_provider_limit_message(state) == ""

    state.pop("last_dispatch")
    assert current_provider_limit_message(state) == ""


def test_terminal_blocked_reason_wins_over_stale_delivery_termination() -> None:
    from harness.provider_limits import current_provider_limit_message

    state = {
        "phase": "terminal-blocked",
        "blocked_reason": "phase_a_readiness_failed",
        "termination_reason": "provider_session_limit",
        "last_dispatch": {"phase_id": "phase3-plan"},
        "provider_limit_message": "STALE provider text",
        "provider_limit_provenance": {
            "phase_id": "phase3-plan",
            "termination_reason": "provider_session_limit",
        },
    }

    assert current_provider_limit_message(state) == ""


def test_clear_provider_limit_removes_message_hint_and_provenance() -> None:
    from harness.provider_limits import clear_provider_limit

    state = {
        "provider_limit_message": "stale",
        "provider_limit_provenance": {
            "phase_id": "phase3-plan",
            "termination_reason": "provider_session_limit",
        },
        "provider_reset_hint": "5pm",
    }

    assert clear_provider_limit(state) is True
    assert "provider_limit_message" not in state
    assert "provider_limit_provenance" not in state
    assert "provider_reset_hint" not in state
