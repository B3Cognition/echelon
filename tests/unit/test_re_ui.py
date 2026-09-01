from __future__ import annotations

from io import StringIO
import json

import pytest


@pytest.mark.unit
def test_re_status_card_uses_shared_echelon_presentation() -> None:
    from echelon.re_ui import print_re_status_card

    output = StringIO()
    print_re_status_card(
        {
            "engine_protocol_version": "2.6",
            "layer_protocol_version": "2.5.1",
            "run_id": "re-l3-child",
            "status": "paused",
            "banner": "L3 PAUSED - CONTINUABLE",
            "selection": {
                "selected_sources": 7,
                "selected_domains": 74,
            },
            "artifact_counts": {
                "adopted": 243,
                "generated_l3": 2,
            },
            "next_action": (
                "run `echelon re continue re-l3-child "
                "--re-time-limit-minutes 1440`"
            ),
        },
        file=output,
    )

    rendered = output.getvalue()
    assert "✈ echelon · RE STATUS" in rendered
    assert "◐ L3 PAUSED - CONTINUABLE" in rendered
    assert "protocol" in rendered and "2.5" in rendered
    assert "outer 2.6 · embedded L3 2.5.1" in rendered
    assert "scope" in rendered and "7 sources · 74 domains" in rendered
    assert "progress" in rendered and "2 generated · 243 adopted" in rendered
    assert "echelon re continue re-l3-child" in rendered


@pytest.mark.unit
def test_re_status_card_surfaces_preflight_failure_without_provider_call() -> None:
    from echelon.re_ui import print_re_status_card

    output = StringIO()
    print_re_status_card(
        {
            "engine_protocol_version": "2.6",
            "layer_protocol_version": "2.5.1",
            "run_id": "re-l3-child",
            "status": "blocked_incomplete",
            "banner": "L3 BLOCKED - AUDIT CONTEXT PREFLIGHT FAILED",
            "selection": {"selected_sources": 7, "selected_domains": 74},
            "artifact_counts": {"adopted": 581, "generated_l3": 7},
            "preflight": {
                "state": "failed",
                "checked_target_count": 8,
                "selected_target_count": 74,
                "max_measured_canonical_json_bytes": 2701823,
                "max_canonical_json_bytes": 196608,
                "provider_dispatch_count": 0,
                "failure": {
                    "scope_kind": "source",
                    "source_id": "pressbox-search",
                    "domain_key": None,
                    "reason_code": "semantic_context_byte_ceiling_exceeded",
                },
            },
            "next_action": (
                "run `echelon re deepen --to L3 --all --from-run re-l2-parent`"
            ),
        },
        file=output,
    )

    rendered = output.getvalue()
    assert "preflight" in rendered
    assert "failed after 8/74 target(s)" in rendered
    assert "2701823 bytes exceeds 196608" in rendered
    assert "no provider call was made" in rendered
    assert "echelon re deepen --to L3 --all --from-run re-l2-parent" in rendered


@pytest.mark.unit
def test_re_progress_tracker_reports_dispatch_acceptance_and_pause() -> None:
    from echelon.re_ui import ReProgressTracker

    tracker = ReProgressTracker(layer="L3", total=74, accepted=1)

    assert tracker.consume({"type": "dispatch_started", "payload": {}}) == (
        "[re] L3 · 1/74 accepted · provider dispatch started"
    )
    assert tracker.consume({"type": "artifact_accepted", "payload": {}}) == (
        "[re] L3 · 2/74 accepted"
    )
    assert tracker.consume(
        {
            "type": "run_paused",
            "payload": {"reason": "resource authorization required"},
        }
    ) == "[re] L3 · paused · resource authorization required"

    l4 = ReProgressTracker(layer="L4", total=2, accepted=0)
    assert l4.consume({"type": "provider_started", "payload": {}}) == (
        "[re] L4 · 0/2 accepted · provider dispatch started"
    )
    assert l4.consume({"type": "accepted_slice_recorded", "payload": {}}) == (
        "[re] L4 · 1/2 accepted"
    )


@pytest.mark.unit
def test_re_status_card_preserves_nested_l1_progress_and_not_run_state() -> None:
    from echelon.re_ui import print_re_status_card

    output = StringIO()
    print_re_status_card(
        {
            "engine_protocol_version": "2.6",
            "run_id": "re-l1",
            "status": "complete",
            "banner": "L1 COMPACT BASELINE COMPLETE",
            "completion_scope": "selected L1 scope only",
            "artifact_counts": {"total": {"accepted": 28, "required": 28}},
            "not_run": {"workspace_synthesis": "not run"},
            "next_action": "none",
        },
        file=output,
    )

    rendered = output.getvalue()
    assert "28/28 accepted" in rendered
    assert "workspace synthesis" in rendered and "not run" in rendered


@pytest.mark.unit
def test_re_progress_session_drains_new_durable_events_on_exit(tmp_path) -> None:
    from echelon.re_ui import re_progress_session

    run_dir = tmp_path / "runs" / "re-live"
    events = run_dir / "v2" / "events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text("", encoding="utf-8")
    output = StringIO()
    document = {
        "engine_protocol_version": "2.5",
        "run_id": run_dir.name,
        "status": "in_progress",
        "banner": "L3 SELECTED SCOPE IN PROGRESS",
        "selection": {"selected_sources": 1, "selected_domains": 2},
        "artifact_counts": {"generated_l3": 0, "adopted": 0},
        "next_action": "run `echelon re continue re-live`",
    }

    with re_progress_session(run_dir, document, file=output, poll_interval=60):
        with events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "dispatch_started", "payload": {}}) + "\n")
            handle.write(json.dumps({"type": "artifact_accepted", "payload": {}}) + "\n")

    rendered = output.getvalue()
    assert "provider dispatch started" in rendered
    assert "[re] L3 · 1/2 accepted" in rendered
