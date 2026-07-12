from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "extension" / "agents" / "exploration" / "golddigger.md"
RE_AGENTS = {
    name: ROOT / "extension" / "agents" / "re" / f"{name}.md"
    for name in (
        "specifier",
        "verifier",
        "expander",
        "validator",
        "checklister",
        "constituter",
    )
}
RE_PHASES = {
    name: ROOT / "extension" / "workflow" / "phases" / f"re-extract-{name}.md"
    for name in (
        "2-specify",
        "3-verify",
        "4-expand",
        "5-validate",
        "6-checklist",
        "7-constitute",
    )
}


class TestGolddiggerTemplates:
    def test_golddigger_prompt_uses_canonical_agent_label(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "agent: speckit-echelon-golddigger (GOLDDIGGER)" in text
        assert "agent: EXTRACT" not in text

    def test_golddigger_mode1_is_one_workspace_flow(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "Mode 1 - Workspace Reverse Engineering" in text
        assert "Mode 1 - Full Reverse Engineering (single-repo)" not in text
        assert "Mode 1 - Full Reverse Engineering (polyrepo)" not in text
        assert "golddigger_mode: workspace-full-re" in text
        assert "## Mode 2 - Focused Domain Deep Dive" in text

    def test_golddigger_uses_planned_workspace_manifests(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "re-analysis-manifest.json" in text
        assert "re-source-index.json" in text
        assert "re-workspace-inputs.json" in text
        assert "workspace-manifest.json" in text
        assert "Do not infer workspace source selection from repository count" in text

    def test_golddigger_uses_explicit_re_runtime_args_not_local_config(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "ALWAYS write extraction config overrides" not in text
        assert "cat > .specify/extensions/echelon/local-config.yml" not in text
        assert "active via `local-config.yml`" not in text
        assert "--profile" in text
        assert "--output" in text
        assert "--manifest" in text
        assert "RE_OUTPUT_DIR" in text

    def test_golddigger_complete_requires_reverse_engineering_specs(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "{RE_OUTPUT_DIR}/workspace/overview.md" in text
        assert "{RE_OUTPUT_DIR}/workspace/relationships.md" in text
        assert "{RE_OUTPUT_DIR}/workspace/contracts.md" in text
        assert "{RE_OUTPUT_DIR}/sources/{source-id}/specs/{domain-id}/spec.md" in text
        assert "specs/000-re-overview" not in text
        assert "NEVER report `golddigger_status: complete` unless reverse-engineering specs exist" in text
        assert "re_overview" in text
        assert "re_specs" in text
        assert "subagent types unavailable" in text
        assert "golddigger_status: partial" in text

    def test_golddigger_mode1_is_not_described_as_survey_only(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "Mode 1 - Workspace Reverse Engineering" in text
        assert "WORKSPACE RE COMPLETE" in text
        assert "SURVEY COMPLETE" not in text
        assert "polyrepo-survey" not in text

    def test_golddigger_preserves_deep_defaults_and_acceptance_gate(self) -> None:
        golddigger = AGENT.read_text(encoding="utf-8")
        specifier = RE_AGENTS["specifier"].read_text(encoding="utf-8")

        assert "--profile full --depth full --max-lines-per-file 5000 --git-history-limit 2500" in golddigger
        assert "at least 5 user stories per domain" in specifier
        for section in (
            "User Scenarios & Testing",
            "Requirements (Functional)",
            "Key Entities",
            "Edge Cases",
            "Source Evidence",
        ):
            assert section in specifier
        assert "shallow_summary_only_spec" in specifier

    def test_re_agents_use_source_owned_and_workspace_paths(self) -> None:
        expected = {
            "specifier": (
                "$RE_OUTPUT_DIR/sources/{source-id}/overview.md",
                "$RE_OUTPUT_DIR/sources/{source-id}/specs/{domain-id}/spec.md",
                "$RE_OUTPUT_DIR/workspace/contracts.md",
            ),
            "verifier": ("$RE_OUTPUT_DIR/quality/{source-id}/coverage-report.md",),
            "expander": ("$RE_OUTPUT_DIR/sources/{source-id}/specs/{domain-id}/spec.md",),
            "validator": ("$RE_OUTPUT_DIR/quality/{source-id}/validation-report.md",),
            "checklister": (
                "$RE_OUTPUT_DIR/sources/{source-id}/specs/{domain-id}/checklist.md",
                "$RE_OUTPUT_DIR/workspace/checklist.md",
            ),
            "constituter": ("$RE_OUTPUT_DIR/workspace/strategy/constitution.md",),
        }
        for name, paths in expected.items():
            text = RE_AGENTS[name].read_text(encoding="utf-8")
            assert "specs/000-re-overview" not in text
            for path in paths:
                assert path in text

    def test_re_phase_contracts_use_staged_workspace_paths(self) -> None:
        for path in RE_PHASES.values():
            text = path.read_text(encoding="utf-8")
            assert "{state.output_dir}" in text
            assert "specs/000-re-overview" not in text

        assert "{state.output_dir}/sources/{source-id}/specs/{domain-id}/spec.md" in RE_PHASES["2-specify"].read_text()
        assert "{state.output_dir}/quality/{source-id}/coverage-report.md" in RE_PHASES["3-verify"].read_text()
        assert "{state.output_dir}/quality/{source-id}/validation-report.md" in RE_PHASES["5-validate"].read_text()
        assert "{state.output_dir}/workspace/checklist.md" in RE_PHASES["6-checklist"].read_text()
        assert "{state.output_dir}/workspace/strategy/constitution.md" in RE_PHASES["7-constitute"].read_text()

    def test_golddigger_treats_empty_sources_as_successful_skip(self) -> None:
        text = AGENT.read_text(encoding="utf-8")

        assert "RE_EMPTY_SOURCES" in text
        assert "empty source roots were skipped successfully" in text
        assert "Empty repositories are a valid no-op, not a failure" in text
        assert "all-empty declared workspace" in text
        assert "no source domain spec is required" in text
