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
