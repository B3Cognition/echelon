"""Tests for `lexicon validate --type structural --artifact <key>`."""
import pytest
from typer.testing import CliRunner

from lexicon.cli import app

runner = CliRunner()

TPL_OK = (
    "## Metadata\nr\n\n"
    "## Feasibility Verdict\nfeasible\n\n"
    "## Key Risks\n- r\n\n"
    "## Kill / Defer / Pass Decision\nPASS\n"
)


@pytest.mark.unit
def test_structural_cli_pass(tmp_path):
    doc = tmp_path / "feasibility.md"
    doc.write_text(TPL_OK)
    res = runner.invoke(
        app,
        ["validate", str(doc), "--type", "structural", "--artifact", "feasibility", "--json"],
    )
    assert res.exit_code == 0 and '"ok": true' in res.stdout


@pytest.mark.unit
def test_structural_cli_fail(tmp_path):
    doc = tmp_path / "feasibility.md"
    doc.write_text("## Metadata\nr\n")  # missing sections + verdict
    res = runner.invoke(
        app,
        ["validate", str(doc), "--type", "structural", "--artifact", "feasibility", "--json"],
    )
    assert res.exit_code != 0 and '"ok": false' in res.stdout
