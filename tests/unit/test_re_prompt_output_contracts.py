from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RE_SPECIFIER = ROOT / "extension" / "agents" / "re" / "specifier.md"
RE_VALIDATOR = ROOT / "extension" / "agents" / "re" / "validator.md"
RE_EXTRACT_2_SPECIFY = (
    ROOT / "extension" / "workflow" / "phases" / "re-extract-2-specify.md"
)
RE_PLANNER = ROOT / "extension" / "agents" / "re" / "planner.md"
RE_PLANNING_1_PLAN = (
    ROOT / "extension" / "workflow" / "phases" / "re-planning-1-plan.md"
)
RE_TASKER = ROOT / "extension" / "agents" / "re" / "tasker.md"
RE_PLANNING_2_TASKS = (
    ROOT / "extension" / "workflow" / "phases" / "re-planning-2-tasks.md"
)
RE_CHECKLISTER = ROOT / "extension" / "agents" / "re" / "checklister.md"
RE_EXTRACT_6_CHECKLIST = (
    ROOT / "extension" / "workflow" / "phases" / "re-extract-6-checklist.md"
)
RE_EXPANDER = ROOT / "extension" / "agents" / "re" / "expander.md"
RE_EXTRACT_4_EXPAND = (
    ROOT / "extension" / "workflow" / "phases" / "re-extract-4-expand.md"
)
RE_ANALYZER = ROOT / "extension" / "agents" / "re" / "analyzer.md"
RE_EXTRACT_1_ANALYZE = (
    ROOT / "extension" / "workflow" / "phases" / "re-extract-1-analyze.md"
)
RE_RETARGET_PHASES = [
    ROOT / "extension" / "workflow" / "phases" / "re-retarget-0-preflight.md",
    ROOT / "extension" / "workflow" / "phases" / "re-retarget-1-input.md",
]


class TestRePromptOutputContracts:
    def test_re_specifier_and_validator_share_behavior_coverage_contract(self) -> None:
        for path in (RE_SPECIFIER, RE_VALIDATOR):
            text = path.read_text(encoding="utf-8")
            assert "Behavior Coverage" in text
            assert "public operations" in text
            assert "configuration keys" in text
            assert "errors and recovery" in text
            assert "Evidence Scope: exhaustive" in text

    def test_re_specifier_uses_exact_behavior_coverage_rows_and_owned_test_scope(self) -> None:
        text = RE_SPECIFIER.read_text(encoding="utf-8")
        categories = (
            "public operations",
            "configuration keys",
            "errors and recovery",
            "boundaries and edge cases",
            "operator-visible behavior",
            "tests",
            "evidence scope",
        )

        for category in categories:
            assert f"`{category}`" in text
        assert "If no tests exist inside the owned domain root, set the `tests` row" in text
        assert "to `not-observed`" in text
        assert "NEVER search outside the owned domain root for tests" in text
        assert "A rejected out-of-scope read is final" in text

    def test_re_specifier_forbids_generalizing_one_case(self) -> None:
        text = RE_SPECIFIER.read_text(encoding="utf-8")
        assert "Never generalize one observed or tested case" in text

    def test_re_analyzer_uses_refresh_manifest_and_source_scoped_outputs(self) -> None:
        for path in [RE_ANALYZER, RE_EXTRACT_1_ANALYZE]:
            text = path.read_text(encoding="utf-8")

            assert "re-analysis-manifest.json" in text
            assert "sources/{source-id}/analysis.json" in text

        analyzer = RE_ANALYZER.read_text(encoding="utf-8")
        assert "controller-owned analysis step" in analyzer
        assert "NEVER invoke repository discovery" in analyzer
        phase = RE_EXTRACT_1_ANALYZE.read_text(encoding="utf-8")
        assert "Summarize only analysis artifacts already present" in phase
        assert "--source-output-root" not in phase

    def test_re_specifier_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_SPECIFIER, RE_EXTRACT_2_SPECIFY]:
            text = path.read_text(encoding="utf-8")

            assert "specs/001-re-auth/spec.md" not in text
            assert "sources/{source-id}/specs/{domain-id}/spec.md" in text

    def test_re_planner_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_PLANNER, RE_PLANNING_1_PLAN]:
            text = path.read_text(encoding="utf-8")

            assert "specs/001-re-auth/plan.md" not in text
            assert "specs/002-re-api/plan.md" not in text
            assert "re/sources/{source-id}/specs/{domain-id}/plan.md" in text
            assert "re/workspace/strategy/constitution.md" in text

    def test_re_tasker_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_TASKER, RE_PLANNING_2_TASKS]:
            text = path.read_text(encoding="utf-8")

            assert "specs/001-re-auth/tasks.md" not in text
            assert "specs/002-re-api/tasks.md" not in text
            assert "re/sources/{source-id}/specs/{domain-id}/tasks.md" in text
            assert "re/workspace/strategy/constitution.md" in text

    def test_re_retarget_uses_canonical_workspace_strategy_paths(self) -> None:
        for path in RE_RETARGET_PHASES:
            text = path.read_text(encoding="utf-8")

            assert "re/workspace/strategy/constitution.md" in text
            assert "re/workspace/strategy/migration-strategy.md" in text
            assert "re/workspace/strategy/risk-matrix.md" in text
            assert "re/workspace/strategy/gap-analysis.md" in text

    def test_re_checklister_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_CHECKLISTER, RE_EXTRACT_6_CHECKLIST]:
            text = path.read_text(encoding="utf-8")

            assert "specs/001-re-auth/checklist.md" not in text
            assert "workspace/checklist.md" in text
            assert "sources/{source-id}/specs/{domain-id}/checklist.md" in text

    def test_re_expander_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_EXPANDER, RE_EXTRACT_4_EXPAND]:
            text = path.read_text(encoding="utf-8")

            assert "specs/004-re-utils/spec.md" not in text
            assert "sources/{source-id}/specs/{domain-id}/spec.md" in text

    def test_re_specify_phase_passes_workspace_source_artifacts(self) -> None:
        text = RE_EXTRACT_2_SPECIFY.read_text(encoding="utf-8")

        assert "{state.output_dir}/re-workspace-inputs.json" in text
        assert "{state.output_dir}/re-source-index.json" in text
        assert "{state.output_dir}/sources/{source-id}/analysis.json" in text
        assert "{state.output_dir}/sources/{source-id}/specs/{domain-id}/spec.md" in text
        assert "canonical source manifests/specs" in text

    def test_re_specifier_rejects_summary_only_specs_at_full_depth(self) -> None:
        text = RE_SPECIFIER.read_text(encoding="utf-8")

        assert "FULL-depth acceptance gate" in text
        assert "User Scenarios & Testing" in text
        assert "Requirements (Functional)" in text
        assert "Key Entities" in text
        assert "Edge Cases" in text
        assert "Source Evidence" in text
        assert "BLOCKED" in text

    def test_re_specifier_excludes_hidden_directories_from_domain_scope(self) -> None:
        text = RE_SPECIFIER.read_text(encoding="utf-8")

        assert "Hidden Directory Exclusion" in text
        assert ".github" in text
        assert "NEVER inspect, cite, summarize, or create a domain" in text

    def test_re_specifier_edits_the_controller_prepared_target(self) -> None:
        text = RE_SPECIFIER.read_text(encoding="utf-8")

        assert "Prepared Target Artifact" in text
        assert "ALWAYS read the controller-prepared target" in text
        assert "NEVER bypass the prepared target artifact" in text
        assert "backup, temporary, alternate, or scratch files" in text

    def test_re_verifier_rejects_specs_without_source_evidence(self) -> None:
        text = (ROOT / "extension" / "agents" / "re" / "verifier.md").read_text(
            encoding="utf-8"
        )

        assert "Source Evidence" in text
        assert "shallow_summary_only" in text
        assert "controller-written eligible, covered, and orphan inventory" in text
        assert "NEVER enumerate source files or recompute coverage" in text

    def test_re_agents_reference_the_deterministic_deep_spec_gate(self) -> None:
        specifier = RE_SPECIFIER.read_text(encoding="utf-8")
        verifier = (ROOT / "extension" / "agents" / "re" / "verifier.md").read_text(
            encoding="utf-8"
        )

        assert "quality/deep-spec-gate.json" in specifier
        assert "quality/deep-spec-gate.json" in verifier
