from pathlib import Path

from typer.testing import CliRunner


def test_reconcile_fulfillment_previews_without_mutating_missing_ledger(
    tmp_path: Path, monkeypatch
) -> None:
    spec_dir = tmp_path / "specs" / "003-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "reconcile-fulfillment", "003-demo"])

    assert result.exit_code == 1
    assert "status: reverify_required" in result.output
    assert not (spec_dir / "verified-fulfillment-ledger.json").exists()


def test_reconcile_fulfillment_is_exposed_in_spec_help() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "--help"])

    assert result.exit_code == 0
    assert "reconcile-fulfillment" in result.output
