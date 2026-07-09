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


def test_verify_spec_init_uses_runs_current_without_latest_run_search() -> None:
    text = (PHASE_DIR / "verify-spec-1-init.md").read_text(encoding="utf-8")

    assert "python -m harness init-verify-spec-run" in text
    assert "Do not read `runs/.current`" in text
    assert "The command owns\n`{orchestration_root}/runs/.current` handling" in text
    assert "Do not list, sort, or search `runs/` to infer the\nlatest run" in text


def test_verify_spec_init_uses_spec_dir_root_for_run_pointer_when_authoritative() -> None:
    text = (PHASE_DIR / "verify-spec-1-init.md").read_text(encoding="utf-8")

    assert "Do not read `runs/.current`, derive `orchestration_root`" in text
    assert "`{orchestration_root}/runs/.current`" in text
    assert "Treat those values as\nauthoritative for all later verify-spec phases" in text


def test_verify_spec_codegraph_uses_deterministic_harness_command() -> None:
    text = (PHASE_DIR / "verify-spec-2-codegraph.md").read_text(encoding="utf-8")

    assert (
        'python -m harness write-codegraph-evidence "{project_root}" '
        '"{verify_run_dir}" "{spec_dir}"'
    ) in text
    assert "{verify_run_dir}/codegraph-analysis.json" in text
    assert "{verify_run_dir}/codegraph-summary.json" in text
    assert "updates `{verify_run_dir}/state.json`" in text
    assert "Do not hand-edit `state.json`" in text


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


def test_verify_spec_stage4_states_parser_conformant_map_schema() -> None:
    phase_text = (PHASE_DIR / "verify-spec-4-map.md").read_text(encoding="utf-8")
    mapper_text = (
        ROOT / "extension" / "agents" / "build" / "implementation-mapper.md"
    ).read_text(encoding="utf-8")

    for text in (phase_text, mapper_text):
        assert (
            "| ID | Implementation Evidence | Test Evidence | CodeGraph Evidence | "
            "Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |"
        ) in text
        assert "Evidence Strength` must be `strong`, `medium`, `weak`, or `none`" in text
        assert "do not write `source_and_test_strong` in `Evidence Strength`" in text
        assert "`Evidence Kind=source_and_test` plus `Evidence Strength=strong`" in text
        assert "| FR-001 | src/file.ts:function | tests/file.test.ts::case | module.symbol | source_and_test | strong | false | high | ... |" in text
        assert "Do not inspect Echelon source code to discover this schema" in text
        assert "moderate" not in text


def test_verify_spec_stage5_references_judgment_prepass() -> None:
    text = (PHASE_DIR / "verify-spec-5-judge.md").read_text(encoding="utf-8")

    assert "judgment-prepass.json" in text
    assert "fallback_ids" in text
    assert "write-fallback-fulfillment-template" in text
    assert "fulfillment-report.fallback.md" in text


def test_verify_spec_stage4_and_stage5_stop_on_missing_deterministic_inputs() -> None:
    map_text = (PHASE_DIR / "verify-spec-4-map.md").read_text(encoding="utf-8")
    judge_text = (PHASE_DIR / "verify-spec-5-judge.md").read_text(encoding="utf-8")

    for text in (map_text, judge_text):
        lowered = text.lower()
        assert "hard stop with" in lowered
        assert "blocked" in lowered
        assert "do not inspect echelon" in lowered
        assert "do not hand-write" in lowered


def test_verify_spec_stage4_degraded_codegraph_skip_is_command_owned() -> None:
    text = (PHASE_DIR / "verify-spec-4-map.md").read_text(encoding="utf-8")

    assert "codegraph_evidence_map: skipped_degraded_codegraph" in text
    assert "Do not\nskip the command manually" in text
    assert "do not hand-edit `state.json`" in text


def test_verify_spec_stage5_forbids_llm_provenance_discovery() -> None:
    text = (PHASE_DIR / "verify-spec-5-judge.md").read_text(encoding="utf-8")

    assert "Ralph stamps `verified_commit` and `verified_at`" in text
    assert "Do not inspect Echelon or harness source code" in text
    assert "Do not search sibling repos under `sources/`" in text
    assert "Do not add or repair provenance frontmatter by hand" in text
    assert "python -m harness inspect-fulfillment-report" in text


def test_spec_guard_prompt_forbids_restatement_of_mechanical_rows() -> None:
    agent_dir = ROOT / "extension" / "agents" / "build"
    text = (agent_dir / "spec-guard.md").read_text(encoding="utf-8")

    assert "judge only IDs listed in `fallback_ids`" in text
    assert "must not emit rows for mechanically decided IDs" in text
