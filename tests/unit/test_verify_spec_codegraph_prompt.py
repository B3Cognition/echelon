"""Prompt contract tests for verify-spec CodeGraph evidence."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
PHASE_DIR = ROOT / "runtime" / "workflow" / "phases"


def test_verify_spec_init_records_project_root_for_deterministic_commands() -> None:
    text = (PHASE_DIR / "verify-spec-1-init.md").read_text(encoding="utf-8")

    assert "- `project_root`" in text


def test_verify_spec_init_accepts_authoritative_spec_dir_argument() -> None:
    text = (PHASE_DIR / "verify-spec-1-init.md").read_text(encoding="utf-8")

    assert "optional `spec_dir=<absolute-or-repo-relative-path>`" in text
    assert "When `spec_dir=` is present, treat it as authoritative" in text
    assert "Do not locate, glob, list, or search `specs/`" in text


def test_verify_spec_init_blocks_when_spec_dir_is_absent() -> None:
    text = (PHASE_DIR / "verify-spec-1-init.md").read_text(encoding="utf-8")

    assert "If `spec_dir=` is absent, hard stop with BLOCKED" in text
    assert "When `spec_dir=` is absent, locate" not in text
    assert "locate\n`specs/{spec_id}-*/`" not in text


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


def test_verify_spec_runs_perlgraph_as_deterministic_structural_evidence() -> None:
    text = (PHASE_DIR / "verify-spec-2-codegraph.md").read_text(encoding="utf-8")

    assert (
        'python -m harness write-perlgraph-evidence "{project_root}" '
        '"{verify_run_dir}" "{spec_dir}"'
    ) in text
    assert "{verify_run_dir}/perlgraph-analysis.json" in text
    assert "{verify_run_dir}/perlgraph-summary.json" in text
    assert "PerlGraph evidence degraded" in text


def test_verify_spec_receipt_phase_does_not_claim_run_completion() -> None:
    text = (PHASE_DIR / "verify-spec-2-codegraph.md").read_text(encoding="utf-8")

    assert "does not write `status` or `completed_at`" in text
    assert "final verify-spec lifecycle\nphase owns completion" in text


def test_verify_spec_codegraph_forbids_prompt_side_discovery() -> None:
    text = (PHASE_DIR / "verify-spec-2-codegraph.md").read_text(encoding="utf-8")

    assert "NEVER locate, inspect, or infer CodeGraph bridge invocation" in text
    assert "do not attempt fallback discovery" in text
    assert "owns deterministic runtime resolution" in text
    assert ".specify/extensions/echelon/scripts/node/codegraph" not in text
    assert ".specify/extensions/echelon/scripts/node/perlgraph" not in text


def test_verify_spec_progress_integrity_does_not_override_fulfillment_status() -> None:
    audit_text = (PHASE_DIR / "verify-spec-3-audit.md").read_text(encoding="utf-8")
    judge_text = (PHASE_DIR / "verify-spec-5-judge.md").read_text(encoding="utf-8")

    assert "bookkeeping evidence, not implementation evidence" in audit_text
    assert "NEVER instruct downstream agents to downgrade" in audit_text
    assert "MUST NOT downgrade an item from `IMPLEMENTED`" in judge_text
    assert "source and executable test evidence satisfy" in judge_text


def test_verify_spec_progress_integrity_stamps_state() -> None:
    text = (PHASE_DIR / "verify-spec-2-progress-integrity.md").read_text(encoding="utf-8")

    assert "writes `progress_integrity: valid`" in text
    assert "writes\n`progress_integrity: invalid`" in text
    assert "{verify_run_dir}/state.json" in text
    assert "Do not ask an LLM to infer or\nrepair progress integrity" in text


def test_verify_spec_stage3_audit_commands_stamp_state() -> None:
    text = (PHASE_DIR / "verify-spec-3-audit.md").read_text(encoding="utf-8")

    assert "stamps `canonical_requirements: ready`" in text
    assert "`canonical_requirements_count`" in text
    assert "stamps `requirement_audit: ready`" in text
    assert "`requirement_audit_count`" in text
    assert "`{verify_run_dir}/state.json`" in text
    assert "If `{verify_run_dir}/state.json` is missing, hard stop with BLOCKED" in text


def test_verify_spec_preserves_runtime_evidence_semantics() -> None:
    map_phase = (PHASE_DIR / "verify-spec-4-map.md").read_text(encoding="utf-8")
    judge_phase = (PHASE_DIR / "verify-spec-5-judge.md").read_text(encoding="utf-8")
    mapper = (
        ROOT / "prosaic" / "subagents" / "echelon.implementation-mapper.md"
    ).read_text(encoding="utf-8")
    guard = (ROOT / "prosaic" / "subagents" / "echelon.spec-guard.md").read_text(
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
        ROOT / "prosaic" / "subagents" / "echelon.implementation-mapper.md"
    ).read_text(encoding="utf-8")

    for text in (phase_text, mapper_text):
        assert (
            "| ID | Verified Implementation Evidence | Verified Test Evidence | CodeGraph Candidates | "
            "Candidate Disposition | Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |"
        ) in text
        assert "schema_version: 2" in text
        assert "Evidence Strength` must be `strong`, `medium`, `weak`, or `none`" in text
        assert "do not write `source_and_test_strong` in `Evidence Strength`" in text
        assert "`Evidence Kind=source_and_test` plus `Evidence Strength=strong`" in text
        assert "| FR-001 | src/file.ts:function | tests/file.test.ts::case | module.symbol | accepted | source_and_test | strong | false | high | ... |" in text
        assert "Do not inspect Echelon source code to discover this schema" in text
        assert "moderate" not in text


def test_verify_spec_stage4_forbids_broad_source_exploration() -> None:
    phase_text = (PHASE_DIR / "verify-spec-4-map.md").read_text(encoding="utf-8")
    lowered = phase_text.lower()

    assert "broad llm/source exploration" not in lowered
    assert "broad source" not in lowered
    assert "summary.fallback_requirement_ids" in phase_text
    assert "bounded fallback queue" in lowered
    assert "do not inspect outside that queue" in lowered


def test_verify_spec_stage4_preserves_weak_codegraph_as_candidate_evidence() -> None:
    phase_text = (PHASE_DIR / "verify-spec-4-map.md").read_text(encoding="utf-8")
    mapper_text = (
        ROOT / "prosaic" / "subagents" / "echelon.implementation-mapper.md"
    ).read_text(encoding="utf-8")

    for text in (phase_text, mapper_text):
        lowered = " ".join(text.lower().split())
        assert "do not dismiss codegraph evidence as useless" in lowered
        assert "fallback inspection refines codegraph candidates" in lowered
        assert "does not replace or ignore them" in lowered
        assert "candidate structural leads, not fulfillment proof" in lowered


def test_verify_spec_stage4_separates_manual_evidence_from_codegraph_evidence() -> None:
    phase_text = (PHASE_DIR / "verify-spec-4-map.md").read_text(encoding="utf-8")
    mapper_text = (
        ROOT / "prosaic" / "subagents" / "echelon.implementation-mapper.md"
    ).read_text(encoding="utf-8")

    for text in (phase_text, mapper_text):
        lowered = " ".join(text.lower().split())
        assert "manual source/test citations" in lowered
        assert "verified implementation evidence and verified test evidence" in lowered
        assert "codegraph candidates must stay in the codegraph candidates cell" in lowered
        assert "candidate disposition" in lowered


def test_verify_spec_stage5_treats_codegraph_candidates_as_context_only() -> None:
    judge_text = (PHASE_DIR / "verify-spec-5-judge.md").read_text(encoding="utf-8")
    guard_text = (ROOT / "prosaic" / "subagents" / "echelon.spec-guard.md").read_text(
        encoding="utf-8"
    )

    for text in (judge_text, guard_text):
        lowered = " ".join(text.lower().split())
        assert "verified implementation evidence" in lowered
        assert "verified test evidence" in lowered
        assert "codegraph candidates" in lowered
        assert "structural leads" in lowered
        assert "do not prove fulfillment" in lowered


def test_verify_spec_stage4_includes_perlgraph_structural_context() -> None:
    phase_text = (PHASE_DIR / "verify-spec-4-map.md").read_text(encoding="utf-8")
    mapper_text = (
        ROOT / "prosaic" / "subagents" / "echelon.implementation-mapper.md"
    ).read_text(encoding="utf-8")

    for text in (phase_text, mapper_text):
        assert "{verify_run_dir}/perlgraph-summary.json" in text
        assert "{verify_run_dir}/perlgraph-analysis.json" in text
        assert "PerlGraph" in text
        assert "low-confidence or dynamic PerlGraph edges" in text
        assert "unsupported_patterns" in text
        assert "candidate future PerlGraph improvements" in text


def test_spec_guard_preserves_perlgraph_uncertainty_semantics() -> None:
    guard = (ROOT / "prosaic" / "subagents" / "echelon.spec-guard.md").read_text(
        encoding="utf-8"
    )

    assert "PerlGraph" in guard
    assert "low-confidence or dynamic PerlGraph" in guard
    assert "unsupported_patterns" in guard
    assert "must not be marked `IMPLEMENTED`" in guard


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
    normalized = " ".join(text.split())
    normalized_lower = normalized.lower()

    assert "Ralph stamps `verified_commit` and `verified_at`" in text
    assert "Provenance is intentionally absent during this direct invocation" in normalized
    assert "do not run `inspect-fulfillment-report`" in normalized_lower
    assert "do not search for a stamping command" in normalized_lower
    assert "do not inspect echelon or harness source code" in normalized_lower
    assert "do not search sibling repos under `sources/`" in normalized_lower
    assert "do not add or repair provenance frontmatter by hand" in normalized_lower
    assert "python -m harness inspect-fulfillment-report" not in text


def test_verify_spec_stage5_validation_stamps_state() -> None:
    text = (PHASE_DIR / "verify-spec-5-judge.md").read_text(encoding="utf-8")

    assert (
        'python -m harness validate-fulfillment-artifacts \\\n'
        '  "{verify_run_dir}/requirement-audit.md" \\\n'
        '  "{spec_dir}/fulfillment-report.md" \\\n'
        '  "{verify_run_dir}/canonical-requirements.json" \\\n'
        '  "{verify_run_dir}/state.json"'
    ) in text
    assert "stamps `fulfillment_artifacts: valid` in `state.json`" in text


def test_verify_spec_final_lifecycle_owns_completion_state() -> None:
    definition = (ROOT / "runtime" / "workflow" / "definition.yaml").read_text(
        encoding="utf-8"
    )
    finalizer = (PHASE_DIR / "verify-spec-7-finalize.md").read_text(
        encoding="utf-8"
    )

    assert "to: verify-spec-7-finalize" in definition
    assert 'python -m harness complete-verify-spec-run "{verify_run_dir}"' in finalizer
    assert "status: complete" in finalizer
    assert "completed_at" in finalizer


def test_verify_spec_reconciliation_routes_through_finalizer_in_prompt_and_definition() -> None:
    definition = (ROOT / "runtime" / "workflow" / "definition.yaml").read_text(
        encoding="utf-8"
    )
    phase_six_definition = definition.split(
        "    - id: verify-spec-6-reconcile", 1
    )[1].split("    - id: verify-spec-7-finalize", 1)[0]
    phase_six_prompt = (PHASE_DIR / "verify-spec-6-reconcile.md").read_text(
        encoding="utf-8"
    )

    assert "to: verify-spec-7-finalize" in phase_six_definition
    assert "to: DONE" not in phase_six_definition
    assert "Proceed to `verify-spec-7-finalize`." in phase_six_prompt
    assert "Proceed to `DONE`." not in phase_six_prompt


def test_spec_guard_prompt_forbids_restatement_of_mechanical_rows() -> None:
    agent_dir = ROOT / "prosaic" / "subagents"
    text = (agent_dir / "echelon.spec-guard.md").read_text(encoding="utf-8")

    assert "judge only IDs listed in `fallback_ids`" in text
    assert "must not emit rows for mechanically decided IDs" in text
