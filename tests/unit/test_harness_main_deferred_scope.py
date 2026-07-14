from __future__ import annotations

from unittest.mock import patch

from harness.deferred_scope import apply_defer


def test_apply_deferred_scope_cli_overlays_report(tmp_path, capsys) -> None:
    spec_dir = tmp_path / "specs" / "906-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("NFR-008\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=NFR-008 depends=none\n",
        encoding="utf-8",
    )
    report = spec_dir / "fulfillment-report.md"
    report.write_text(
        "| ID | Status | Evidence |\n| --- | --- | --- |\n"
        "| NFR-008 | DEVIATED | no valid palette |\n",
        encoding="utf-8",
    )
    apply_defer(spec_dir, ["NFR-008"], reason="contradictory contrast rule")

    from harness.__main__ import main

    with patch("sys.argv", ["python -m harness", "apply-deferred-scope", str(spec_dir), str(report)]):
        main()

    assert "OK: applied deferred scope to 1 fulfillment row" in capsys.readouterr().out
    assert "DEFERRED_SCOPE" in report.read_text(encoding="utf-8")
