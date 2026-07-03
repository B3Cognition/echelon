from echelon import cli
from pathlib import Path


def test_verify_spec_command_registered():
    assert cli.SKILL_MAP["verify-spec"] == "echelon.verify-spec"
    assert "spec verify <spec_id> [--reconcile] [--dry-run]" in cli.USAGE


def test_verify_spec_reconciliation_documented_in_readme():
    readme = Path(__file__).resolve().parents[2] / "README.md"
    text = readme.read_text(encoding="utf-8")

    assert "--reconcile" in text
    assert "--reconcile --dry-run" in text


def test_reopen_command_registered():
    assert cli.SKILL_MAP["reopen"] == "echelon.reopen"
    assert "spec reopen <spec_id>" in cli.USAGE
