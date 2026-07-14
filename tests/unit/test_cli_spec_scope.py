from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner


def _spec(tmp_path: Path) -> Path:
    spec_dir = tmp_path / "specs" / "906-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("FR-001\nNFR-008\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-016 complexity=standard phase=build req=NFR-008,FR-001 depends=none\n",
        encoding="utf-8",
    )
    return spec_dir


def test_spec_defer_dry_run_lists_direct_and_related_effects(tmp_path: Path, monkeypatch) -> None:
    _spec(tmp_path)
    monkeypatch.chdir(tmp_path)
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["spec", "defer", "906", "NFR-008", "--reason", "contradictory", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "direct IDs: NFR-008" in result.output
    assert "deferred tasks: T-016" in result.output
    assert "FR-001 remains active" in result.output
    assert not (tmp_path / "specs" / "906-demo" / "deferred-scope.json").exists()


def test_spec_plan_reactivates_a_deferred_requirement(tmp_path: Path, monkeypatch) -> None:
    _spec(tmp_path)
    monkeypatch.chdir(tmp_path)
    from echelon.cli_app import app

    runner = CliRunner()
    deferred = runner.invoke(
        app,
        ["spec", "defer", "906", "NFR-008", "--reason", "contradictory"],
    )
    planned = runner.invoke(app, ["spec", "plan", "906", "NFR-008"])

    assert deferred.exit_code == 0, deferred.output
    assert planned.exit_code == 0, planned.output
    assert "planned scope" in planned.output.lower()
