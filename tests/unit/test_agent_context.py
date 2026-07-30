from harness.agent_context import (
    parse_context_pack_item,
    policy_for_context,
    resolve_context_render_mode,
)


def test_parse_context_pack_item_extracts_filters_and_path() -> None:
    selector = parse_context_pack_item(
        ".specify/squad/reasoning-journal.jsonl [type=routing_decision, phase=phase1-what]"
    )

    assert selector.path_ref == ".specify/squad/reasoning-journal.jsonl"
    assert selector.filters == {
        "type": "routing_decision",
        "phase": "phase1-what",
    }


def test_parse_context_pack_item_preserves_glob_path() -> None:
    selector = parse_context_pack_item("adr/ADR-*.md")

    assert selector.path_ref == "adr/ADR-*.md"
    assert selector.filters == {}


def test_resolve_context_render_mode_defaults_to_bounded() -> None:
    assert resolve_context_render_mode({}) == "bounded"


def test_resolve_context_render_mode_accepts_legacy() -> None:
    assert resolve_context_render_mode({"ECHELON_CONTEXT_RENDER_MODE": "legacy"}) == "legacy"


def test_resolve_context_render_mode_rejects_unknown() -> None:
    assert resolve_context_render_mode({"ECHELON_CONTEXT_RENDER_MODE": "strange"}) == "bounded"


def test_policy_for_why2_preserves_spec() -> None:
    policy = policy_for_context(
        phase_id="phase1-why2",
        agent_id="speckit-echelon-sage",
        mode="WHY2",
        path_ref="{spec_dir}/spec.md",
    )

    assert policy.criticality == "must_preserve"
    assert policy.renderer == "full_file"
    assert policy.overflow_action == "legacy_fallback_warning"


def test_policy_for_journal_history_is_bounded() -> None:
    policy = policy_for_context(
        phase_id="phase1-why2",
        agent_id="speckit-echelon-sage",
        mode="WHY2",
        path_ref=".specify/squad/reasoning-journal.jsonl",
    )

    assert policy.criticality == "history"
    assert policy.renderer == "filtered_journal"
    assert policy.overflow_action == "truncate_with_notice"
