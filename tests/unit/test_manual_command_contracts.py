from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMAND_DIR = ROOT / "extension" / "commands"


class TestManualCommandContracts:
    def test_manual_specialist_commands_use_canonical_commander_journal_label(
        self,
    ) -> None:
        for filename in [
            "echelon.innovate.md",
            "echelon.ground.md",
            "echelon.investigate.md",
        ]:
            text = (COMMAND_DIR / filename).read_text(encoding="utf-8")

            assert "agent: speckit-echelon-commander (COMMANDER)" in text
            assert "agent: MANAGER" not in text
            assert "  output_files: []\n" in text

    def test_manual_specialist_commands_use_resolved_spec_dir_for_outputs(
        self,
    ) -> None:
        expected_outputs = {
            "echelon.innovate.md": ["Produce outputs in `{spec_dir}/`"],
            "echelon.ground.md": [
                "Produce outputs in `{spec_dir}/`",
                "Full report:      {spec_dir}/reality-check.md",
            ],
            "echelon.investigate.md": [
                "Produce outputs in `{spec_dir}/`",
                "Full report:     {spec_dir}/investigation/{topic}.md",
            ],
        }

        for filename, expected_lines in expected_outputs.items():
            text = (COMMAND_DIR / filename).read_text(encoding="utf-8")

            assert "Produce outputs in `.specify/specs/{spec_dir}/`" not in text
            assert ".specify/specs/{spec_dir}/reality-check.md" not in text
            assert ".specify/specs/{spec_dir}/investigation/{topic}.md" not in text
            for expected_line in expected_lines:
                assert expected_line in text

    def test_change_command_uses_resolved_spec_dir_for_context(self) -> None:
        text = (COMMAND_DIR / "echelon.change.md").read_text(encoding="utf-8")

        assert ".specify/specs/{feature}/" not in text
        assert "`{spec_dir}/spec.md`" in text
        assert "`{spec_dir}/adrs/`" in text

    def test_status_command_delegates_to_python_harness(self) -> None:
        text = (COMMAND_DIR / "echelon.status.md").read_text(encoding="utf-8")

        assert "echelon spec status" in text
        assert "Python harness owns state discovery, artifact inventory" in text
        assert "Do not inspect run" in text
        assert ".specify/specs/{spec_id}-*/" not in text
        assert "specs/{spec_id}-*/" not in text

    def test_manual_specialist_commands_require_state_spec_dir(self) -> None:
        for filename in ["echelon.innovate.md", "echelon.ground.md"]:
            text = (COMMAND_DIR / filename).read_text(encoding="utf-8")

            assert "Treat `state.json.spec_dir` as authoritative" in text
            assert "Do not locate, glob, search, list, or infer `specs/{spec_id}-*/`" in text
            assert "Active squad state is missing spec_dir" in text
            assert "If `state.json.spec_dir` is absent, locate" not in text

    def test_status_command_does_not_duplicate_artifact_discovery(self) -> None:
        text = (COMMAND_DIR / "echelon.status.md").read_text(encoding="utf-8")

        assert "Do not inspect run\n" in text
        assert "directories, `state.json`, spec artifacts" in text
        assert "Python harness owns state discovery" in text
        assert "Python harness owns state discovery, artifact inventory" in text
        assert "If `state.json.spec_dir` is present" not in text
        assert "If `state.json.spec_dir` is present, use it as the spec directory" not in text
        assert "Only fall back to `specs/{spec_id}-*/`" not in text

    def test_feedback_command_locates_specs_from_workspace_specs_dir(self) -> None:
        text = (COMMAND_DIR / "echelon.feedback.md").read_text(encoding="utf-8")

        assert ".specify/specs/" not in text
        assert "Scan `specs/`" in text
        assert "Check specs/ for available IDs." in text

    def test_review_command_accepts_authoritative_spec_dir(self) -> None:
        text = (COMMAND_DIR / "echelon.review.md").read_text(encoding="utf-8")

        assert "`spec_dir`" in text
        assert "treat it as authoritative" in text
        assert "do not locate, glob, or\nsearch for `specs/{spec_id}-*/`" in text
        assert "`{spec_dir}/spec.md`" in text
        assert "`{spec_dir}/tasks.md`" in text
        assert "Harness Review Input" in text
        assert "review_staging_dir" in text
        assert "review_status_file" in text
        assert "tasks-append.md" in text
        assert text.count('"review_task_id"') >= 3
        assert "**Title:** RF7-T1" in text
        assert "**Title:** RF7-T2" in text
        assert "**Title:** RF7-T3" in text
        assert "gh api" not in text
        assert "glab api" not in text
        assert "```bash" not in text
        assert "ls \"{spec_dir}\"/review-fix-*.md" not in text
        assert "`specs/{spec_id}-{spec_name}/spec.md`" not in text
        assert "`specs/{spec_id}-{spec_name}/tasks.md`" not in text
        assert "Never checkout, switch, or stash branches" in text
        assert "git checkout" not in text
        assert "git stash" not in text

    def test_harness_run_command_accepts_authoritative_spec_dir(self) -> None:
        text = (COMMAND_DIR / "echelon.harness-run.md").read_text(encoding="utf-8")

        assert "| `spec_dir` |" in text
        assert "Treat `spec_dir` as authoritative" in text
        assert "Do not locate, glob, search, list, or infer" in text
        assert "Harness run missing resolved spec_dir" in text
        assert "`{spec_dir}/spec.md`" in text
        assert "`{spec_dir}/tasks.md`" in text
        assert "`{spec_dir}/coverage-map.md`" in text
        assert 'LESSONS_FILE="{spec_dir}/lessons.md"' in text
        assert 'SPEC_DIR_REL="${SPEC_DIR#$(pwd)/}"' in text
        assert 'SPEC_DIR_REL="${SPEC_DIR_REL#$(pwd)/}"' in text
        assert "`specs/{spec_id}-*/spec.md`" not in text
        assert "`specs/{spec_id}-*/tasks.md`" not in text
        assert "LESSONS_FILE=\"specs/{spec_id}-{spec_name}/lessons.md\"" not in text

    def test_investigate_command_uses_workspace_specs_for_standalone_runs(self) -> None:
        text = (COMMAND_DIR / "echelon.investigate.md").read_text(encoding="utf-8")

        assert ".specify/specs/investigation-{timestamp}/" not in text
        assert "specs/investigation-{timestamp}/" in text

    def test_investigate_command_tracks_registered_investigator_role(self) -> None:
        text = (COMMAND_DIR / "echelon.investigate.md").read_text(encoding="utf-8")

        assert 'Add `"SCIENTIST"` to `active_specialists`' not in text
        assert 'Add `"INVESTIGATOR"` to `active_specialists`' in text
        assert "active_specialists: <existing active_specialists plus SCIENTIST>" not in text
        assert "active_specialists: <existing active_specialists plus INVESTIGATOR>" in text

    def test_cicd_command_is_retired_and_does_not_delegate_to_run(self) -> None:
        text = (COMMAND_DIR / "echelon.cicd.md").read_text(encoding="utf-8")

        assert "Retired" in text
        assert "speckit-echelon-run" not in text
