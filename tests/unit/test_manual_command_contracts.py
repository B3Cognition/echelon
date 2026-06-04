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
