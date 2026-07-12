from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RE_SPECIFIER = ROOT / "extension" / "agents" / "re" / "specifier.md"
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


class TestRePromptOutputContracts:
    def test_re_analyzer_uses_refresh_manifest_and_source_scoped_outputs(self) -> None:
        for path in [RE_ANALYZER, RE_EXTRACT_1_ANALYZE]:
            text = path.read_text(encoding="utf-8")

            assert "re-analysis-manifest.json" in text
            assert "--source-output-root" in text
            assert "sources/{source-id}/analysis.json" in text

        analyzer = RE_ANALYZER.read_text(encoding="utf-8")
        assert '--profile "$RE_PROFILE"' in analyzer
        assert '--depth "$RE_DEPTH"' in analyzer
        assert '--max-lines-per-file "$RE_MAX_LINES"' in analyzer
        assert '--git-history-limit "$RE_GIT_LIMIT"' in analyzer

    def test_re_specifier_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_SPECIFIER, RE_EXTRACT_2_SPECIFY]:
            text = path.read_text(encoding="utf-8")

            assert "specs/001-re-auth/spec.md" not in text
            assert "specs/NNN-re-{domain}/spec.md" in text

    def test_re_planner_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_PLANNER, RE_PLANNING_1_PLAN]:
            text = path.read_text(encoding="utf-8")

            assert "specs/001-re-auth/plan.md" not in text
            assert "specs/002-re-api/plan.md" not in text
            assert "specs/NNN-re-{domain}/plan.md" in text

    def test_re_tasker_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_TASKER, RE_PLANNING_2_TASKS]:
            text = path.read_text(encoding="utf-8")

            assert "specs/001-re-auth/tasks.md" not in text
            assert "specs/002-re-api/tasks.md" not in text
            assert "specs/NNN-re-{domain}/tasks.md" in text

    def test_re_checklister_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_CHECKLISTER, RE_EXTRACT_6_CHECKLIST]:
            text = path.read_text(encoding="utf-8")

            assert "specs/001-re-auth/checklist.md" not in text
            assert "specs/000-re-overview/checklist.md" in text
            assert "specs/NNN-re-{domain}/checklist.md" in text

    def test_re_expander_uses_domain_placeholder_in_output_examples(self) -> None:
        for path in [RE_EXPANDER, RE_EXTRACT_4_EXPAND]:
            text = path.read_text(encoding="utf-8")

            assert "specs/004-re-utils/spec.md" not in text
            assert "specs/NNN-re-{domain}/spec.md" in text

    def test_re_specify_phase_passes_polyrepo_full_artifacts(self) -> None:
        text = RE_EXTRACT_2_SPECIFY.read_text(encoding="utf-8")

        assert "{state.output_dir}/workspace-manifest.json" in text
        assert "{state.output_dir}/re-source-index.json" in text
        assert "{state.output_dir}/{source}/analysis.json" in text
        assert "{state.output_dir}/{source}/codegraph-summary.json" in text
        assert "{state.output_dir}/{source}/codegraph-analysis.json" in text
        assert "root `analysis.json` is only an aggregate index" in text

    def test_re_specifier_rejects_summary_only_specs_at_full_depth(self) -> None:
        text = RE_SPECIFIER.read_text(encoding="utf-8")

        assert "FULL-depth acceptance gate" in text
        assert "User Scenarios & Testing" in text
        assert "Requirements (Functional)" in text
        assert "Key Entities" in text
        assert "Edge Cases" in text
        assert "Source Evidence" in text
        assert "BLOCKED" in text

    def test_re_verifier_rejects_specs_without_source_evidence(self) -> None:
        text = (ROOT / "extension" / "agents" / "re" / "verifier.md").read_text(
            encoding="utf-8"
        )

        assert "Source Evidence" in text
        assert "coverage_pct: 0" in text
        assert "shallow_summary_only" in text
