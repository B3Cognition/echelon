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
    assert "✈ echelon · RE v2 · L3 SEMANTIC AUDIT" in rendered
    assert "◐ L3 PAUSED - CONTINUABLE" in rendered
    assert "outer 2.6" not in rendered
    assert "embedded L3 2.5.1" not in rendered
    assert "scope" in rendered and "7 sources · 74 domains" in rendered
    assert "progress" in rendered and "2 generated · 243 adopted" in rendered
    assert "echelon re continue re-l3-child" in rendered


@pytest.mark.unit
@pytest.mark.parametrize(
    ("document", "title"),
    (
        (
            {
                "target_layer": "L1",
                "status": "complete",
                "banner": "L1 COMPACT BASELINE COMPLETE",
            },
            "RE v2 · L1 COMPACT BASELINE",
        ),
        (
            {
                "target_layer": "L2",
                "status": "complete",
                "banner": "L2 BEHAVIORAL DEEPENING COMPLETE",
            },
            "RE v2 · L2 BEHAVIORAL DEEPENING",
        ),
        (
            {
                "target_layer": "L4",
                "status": "in_progress",
                "banner": "L4 EXHAUSTIVE RE IN PROGRESS",
            },
            "RE v2 · L4 EXHAUSTIVE ANALYSIS",
        ),
        (
            {
                "synthesis_status": "in_progress",
                "status": "in_progress",
            },
            "RE v2 · WORKSPACE SYNTHESIS",
        ),
    ),
)
def test_re_status_card_uses_public_stage_names_without_internal_protocols(
    document: dict[str, object],
    title: str,
) -> None:
    from echelon.re_ui import print_re_status_card

    output = StringIO()
    print_re_status_card(
        {
            "engine_protocol_version": "2.7",
            "layer_protocol_version": "2.5.1",
            "run_id": "re-stage",
            "selection": {"selected_sources": 1, "selected_domains": 1},
            "artifact_counts": {"generated": 0, "adopted": 0},
            **document,
        },
        file=output,
    )

    rendered = output.getvalue()
    assert f"✈ echelon · {title}" in rendered
    assert "protocol" not in rendered.lower()
    assert "2.5.1" not in rendered
    assert "2.7" not in rendered


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
def test_re_error_uses_public_version_and_hides_internal_protocol_number() -> None:
    from echelon.re_ui import print_re_error

    output = StringIO()
    print_re_error(
        "echelon re continue",
        ValueError("protocol-2.5 run cannot continue"),
        file=output,
    )

    rendered = output.getvalue()
    assert "✈ echelon · RE v2 · ERROR" in rendered
    assert "RE v2 run cannot continue" in rendered
    assert "protocol-2.5" not in rendered


@pytest.mark.unit
def test_l3_progress_total_includes_domain_and_source_audit_targets() -> None:
    from echelon.re_ui import _accepted_total

    assert _accepted_total(
        {
            "selection": {"selected_domains": 74},
            "artifact_counts": {"generated_l3": 7, "adopted": 581},
            "preflight": {"selected_target_count": 81},
        }
    ) == (7, 81)
    assert _accepted_total(
        {
            "selection": {"selected_domains": 74},
            "artifact_counts": {"generated_l3": 109, "adopted": 581},
            "preflight": {"selected_target_count": 81},
        }
    ) == (81, 81)


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
    assert tracker.consume(
        {
            "type": "run_completed",
            "payload": {"reason": "all requested protocol-2.5.1 artifacts are accepted"},
        }
    ) == "[re] L3 · completed · all requested RE v2 artifacts are accepted"

    l4 = ReProgressTracker(layer="L4", total=2, accepted=0)
    assert l4.consume({"type": "provider_started", "payload": {}}) == (
        "[re] L4 · 0/2 accepted · provider dispatch started"
    )
    assert l4.consume({"type": "accepted_slice_recorded", "payload": {}}) == (
        "[re] L4 · 1/2 accepted"
    )

    complete = ReProgressTracker(layer="L3", total=81, accepted=81)
    assert complete.consume({"type": "artifact_accepted", "payload": {}}) == (
        "[re] L3 · 81/81 accepted"
    )


@pytest.mark.unit
def test_re_progress_heartbeat_claims_provider_work_only_during_dispatch() -> None:
    from echelon.re_ui import ReProgressTracker

    tracker = ReProgressTracker(layer="L3", total=81, accepted=7)

    assert tracker.heartbeat() == (
        "[re] L3 · 7/81 accepted · controller still working"
    )
    tracker.consume({"type": "dispatch_started", "payload": {}})
    assert tracker.heartbeat() == (
        "[re] L3 · 7/81 accepted · provider still working"
    )
    tracker.consume({"type": "dispatch_observed", "payload": {}})
    assert tracker.heartbeat() == (
        "[re] L3 · 7/81 accepted · controller still working"
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
