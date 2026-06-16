"""Prompt contract tests for verify-spec CodeGraph evidence."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
PHASE_DIR = ROOT / "extension" / "workflow" / "phases"


def test_verify_spec_init_records_project_root_for_deterministic_commands() -> None:
    text = (PHASE_DIR / "verify-spec-1-init.md").read_text(encoding="utf-8")

    assert "- `project_root`" in text


def test_verify_spec_init_accepts_authoritative_spec_dir_argument() -> None:
    text = (PHASE_DIR / "verify-spec-1-init.md").read_text(encoding="utf-8")

    assert "optional `spec_dir=<absolute-or-repo-relative-path>`" in text
    assert "When `spec_dir=` is present, treat it as authoritative" in text
    assert "do not locate or\nglob `specs/{spec_id}-*/`" in text


def test_verify_spec_init_accepts_scoped_verify_arguments() -> None:
    text = (PHASE_DIR / "verify-spec-1-init.md").read_text(encoding="utf-8")

    assert "optional `scope=scoped`" in text
    assert "optional `scoped_ids=<comma-separated requirement IDs>`" in text
    assert "`verify_scope`" in text
    assert "`scoped_ids`" in text
    assert "`base_full_verify_commit`" in text


def test_verify_spec_codegraph_uses_deterministic_harness_command() -> None:
    text = (PHASE_DIR / "verify-spec-2-codegraph.md").read_text(encoding="utf-8")

    assert (
        'python -m harness write-codegraph-evidence "{project_root}" '
        '"{verify_run_dir}" "{spec_dir}"'
    ) in text
    assert "{verify_run_dir}/codegraph-analysis.json" in text
    assert "{verify_run_dir}/codegraph-summary.json" in text


def test_verify_spec_codegraph_forbids_prompt_side_discovery() -> None:
    text = (PHASE_DIR / "verify-spec-2-codegraph.md").read_text(encoding="utf-8")

    assert "NEVER locate, inspect, or infer CodeGraph bridge invocation" in text
    assert "do not attempt fallback discovery" in text


def test_verify_spec_progress_integrity_does_not_override_fulfillment_status() -> None:
    audit_text = (PHASE_DIR / "verify-spec-3-audit.md").read_text(encoding="utf-8")
    judge_text = (PHASE_DIR / "verify-spec-5-judge.md").read_text(encoding="utf-8")

    assert "bookkeeping evidence, not implementation evidence" in audit_text
    assert "NEVER instruct downstream agents to downgrade" in audit_text
    assert "MUST NOT downgrade an item from `IMPLEMENTED`" in judge_text
    assert "source and executable test evidence satisfy" in judge_text


def test_verify_spec_preserves_runtime_evidence_semantics() -> None:
    map_phase = (PHASE_DIR / "verify-spec-4-map.md").read_text(encoding="utf-8")
    judge_phase = (PHASE_DIR / "verify-spec-5-judge.md").read_text(encoding="utf-8")
    mapper = (
        ROOT / "extension" / "agents" / "build" / "implementation-mapper.md"
    ).read_text(encoding="utf-8")
    guard = (ROOT / "extension" / "agents" / "build" / "spec-guard.md").read_text(
        encoding="utf-8"
    )

    for text in (map_phase, mapper):
        assert "evidence_kind" in text
        assert "evidence_strength" in text
        assert "assertion_only" in text

    for text in (judge_phase, guard):
        lowered = text.lower()
        assert "runtime threshold" in lowered
        assert "measured" in lowered
        assert "runtime" in lowered or "ci artifact" in lowered
        assert "must not" in lowered
        assert "assertion_only" in lowered
