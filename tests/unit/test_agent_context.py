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

from harness.agent_context import (
    PromptRenderReport,
    RenderedSection,
    build_context_budget_report,
    write_context_budget_report,
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


def test_render_contracts_directory_preserves_manifest_when_manifest_exceeds_cap(
    tmp_path: Path,
) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    for index in range(300):
        (contracts / f"contract-{index:03d}.md").write_text(
            f"BODY-{index:03d}",
            encoding="utf-8",
        )
    policy = ContextPolicy("must_preserve", "directory_bounded_files", 128, "manifest_only")

    section = render_context_path("contracts/", contracts, policy, {}, phase_id="phase3-sentinel")

    assert "## Directory manifest" in section.text
    assert "- contract-000.md" in section.text
    assert "- contract-299.md" in section.text
    assert "BODY-000" not in section.text
    assert "[Directory bodies truncated: included 0/300 files]" in section.text
    assert section.omitted["files"] == 300
    assert section.omitted["included_files"] == 0
    assert section.omitted["truncated"] == "true"


def test_render_file_keeps_section_within_cap(tmp_path: Path) -> None:
    document = tmp_path / "document.md"
    document.write_text("content" * 100, encoding="utf-8")
    policy = ContextPolicy("important", "full_file", 32, "truncate_with_notice")

    section = render_context_path("document.md", document, policy, {})

    assert section.bytes <= 32


def test_render_journal_keeps_section_within_tiny_cap(tmp_path: Path) -> None:
    journal = tmp_path / "reasoning-journal.jsonl"
    journal.write_text(json.dumps({"type": "decision", "phase": "phase1-what"}) + "\n", encoding="utf-8")

    section = render_journal(journal, {}, cap_bytes=8)

    assert section.bytes <= 8


def test_render_directory_keeps_body_content_within_remaining_cap(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "a.md").write_text("a" * 5000, encoding="utf-8")
    policy = ContextPolicy("must_preserve", "directory_bounded_files", 64, "manifest_only")

    section = render_context_path("contracts/", contracts, policy, {})

    assert "- a.md" in section.text
    assert "a" * 100 not in section.text


def test_render_directory_marks_unreadable_child_unavailable(tmp_path: Path, monkeypatch) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    readable = contracts / "a.md"
    unreadable = contracts / "b.md"
    readable.write_text("readable", encoding="utf-8")
    unreadable.write_text("unreadable", encoding="utf-8")
    original_read_text = Path.read_text

    def fail_unreadable(path: Path, *args, **kwargs):
        if path == unreadable:
            raise OSError("permission denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_unreadable)
    policy = ContextPolicy("must_preserve", "directory_bounded_files", 4096, "manifest_only")

    section = render_context_path("contracts/", contracts, policy, {})

    assert "File unavailable" in section.text


def test_build_context_budget_report_compares_legacy_and_bounded() -> None:
    report: PromptRenderReport = build_context_budget_report(
        phase_id="phase1-why2",
        agent_id="speckit-echelon-sage",
        mode="WHY2",
        selected_render_mode="bounded",
        legacy_sections=[
            RenderedSection("state.json", "x" * 1000, 1000, {}),
            RenderedSection("reasoning-journal.jsonl", "x" * 3000, 3000, {}),
        ],
        bounded_sections=[
            RenderedSection("state.json", "x" * 200, 200, {"projection": "compact"}),
            RenderedSection("reasoning-journal.jsonl", "x" * 500, 500, {"included": 2}),
        ],
        strict=False,
    )

    assert report["phase"] == "phase1-why2"
    assert report["selected_render_mode"] == "bounded"
    assert report["legacy"]["bytes"] == 4000
    assert report["bounded"]["bytes"] == 700
    assert report["savings"]["bytes"] == 3300
    assert report["savings"]["reduction_pct"] == 82
    assert all("text" not in section for section in report["legacy"]["top_sections"])


def test_write_context_budget_report_persists_json(tmp_path: Path) -> None:
    path = write_context_budget_report(
        tmp_path,
        {
            "phase": "phase1-why2",
            "agent": "speckit-echelon-sage",
            "mode": "WHY2",
            "selected_render_mode": "bounded",
            "legacy": {"bytes": 10, "approx_tokens": 3, "top_sections": []},
            "bounded": {"bytes": 5, "approx_tokens": 2, "top_sections": []},
            "savings": {"bytes": 5, "approx_tokens": 1, "reduction_pct": 50},
        },
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.parent == tmp_path / "context-budget"
    assert payload["phase"] == "phase1-why2"


def test_write_context_budget_report_skips_existing_sequence_gaps(tmp_path: Path) -> None:
    out_dir = tmp_path / "context-budget"
    out_dir.mkdir()
    for sequence in (1, 3):
        (out_dir / f"dispatch-{sequence:04d}-phase1-why2-agent.json").write_text("{}", encoding="utf-8")

    path = write_context_budget_report(tmp_path, {"phase": "phase1-why2", "agent": "agent"})

    assert path.name == "dispatch-0002-phase1-why2-agent.json"
    assert path.read_text(encoding="utf-8") != "{}"
