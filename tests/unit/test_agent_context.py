import json
from pathlib import Path

from harness.agent_context import (
    parse_context_pack_item,
    policy_for_context,
    resolve_context_render_mode,
    ContextPolicy,
    compact_state_projection,
    render_context_path,
    render_journal,
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


def test_render_journal_filters_phase_and_type(tmp_path: Path) -> None:
    journal = tmp_path / "reasoning-journal.jsonl"
    journal.write_text(
        "\n".join(
            [
                json.dumps({"type": "decision", "phase": "phase1-what", "data": {"keep": True}}),
                json.dumps({"type": "decision", "phase": "phase1-old", "data": {"drop": True}}),
                json.dumps({"type": "insight", "phase": "phase1-what", "data": {"drop": True}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    section = render_journal(
        journal,
        {"type": "routing_decision", "phase": "phase1-what"},
        cap_bytes=4096,
    )

    assert '"keep": true' in section.text
    assert "phase1-old" not in section.text
    assert '"type": "insight"' not in section.text
    assert section.omitted["matched"] == 1


def test_render_journal_supports_phase_wildcard(tmp_path: Path) -> None:
    journal = tmp_path / "reasoning-journal.jsonl"
    journal.write_text(
        json.dumps({"type": "decision", "phase": "phase1-why1"}) + "\n"
        + json.dumps({"type": "decision", "phase": "phase2-decide"}) + "\n",
        encoding="utf-8",
    )

    section = render_journal(journal, {"phase": "phase1-*"}, cap_bytes=4096)

    assert "phase1-why1" in section.text
    assert "phase2-decide" not in section.text


def test_compact_state_projection_excludes_large_ledgers() -> None:
    state = {
        "phase": "phase1-why2",
        "spec_id": "001-demo",
        "squad_dir": "/tmp/run",
        "issue_resolution_ledger": {
            "ISS-1": {"status": "validated", "guidance": "x" * 10_000},
        },
        "token_ledger": {"dispatches": [{"raw": "x" * 10_000}]},
    }

    projection = compact_state_projection(state, "phase1-why2")

    assert projection["phase"] == "phase1-why2"
    assert projection["issue_resolution_statuses"] == {"ISS-1": "validated"}
    assert "issue_resolution_ledger" not in projection
    assert "token_ledger" not in projection


def test_render_contracts_directory_preserves_manifest_when_body_capped(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "a.md").write_text("# A\n" + "a" * 5000, encoding="utf-8")
    (contracts / "b.md").write_text("# B\n" + "b" * 5000, encoding="utf-8")
    policy = ContextPolicy("must_preserve", "directory_bounded_files", 512, "manifest_only")

    section = render_context_path("contracts/", contracts, policy, {}, phase_id="phase3-sentinel")

    assert "## Directory manifest" in section.text
    assert "a.md" in section.text
    assert "b.md" in section.text
    assert section.omitted["truncated"] == "true"
