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

    def test_active_run_commands_locate_specs_from_workspace_specs_dir(self) -> None:
        for filename in [
            "echelon.innovate.md",
            "echelon.ground.md",
            "echelon.status.md",
        ]:
            text = (COMMAND_DIR / filename).read_text(encoding="utf-8")

            assert ".specify/specs/{spec_id}-*/" not in text
            assert "specs/{spec_id}-*/" in text

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
