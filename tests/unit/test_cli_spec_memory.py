from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_spec_memory_help_is_exposed() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "--help"])

    assert result.exit_code == 0
    assert "mine" in result.output
    assert "audit" in result.output
    assert "refresh" in result.output


@pytest.mark.unit
def test_spec_memory_audit_json_exit_zero_for_warn(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_audit import SpecMemoryAuditReport

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        lambda project_root, selector, probe_retrieval=False: SpecMemoryAuditReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="warn",
            expected_count=1,
            present_current_count=1,
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "audit", "003-demo", "--json"])

    assert result.exit_code == 0
    assert '"status": "warn"' in result.output


@pytest.mark.unit
def test_spec_memory_audit_exit_codes(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_audit import SpecMemoryAuditReport

    monkeypatch.chdir(tmp_path)

    def fake_audit(project_root, selector, probe_retrieval=False):
        return SpecMemoryAuditReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing=None,
            palace_path=None,
            status="unavailable",
            expected_count=0,
            present_current_count=0,
        )

    monkeypatch.setattr("echelon.mempalace_audit.audit_spec_memory", fake_audit, raising=False)
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "audit", "003-demo"])

    assert result.exit_code == 2


@pytest.mark.unit
def test_main_preserves_unavailable_memory_audit_exit_code(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_audit import SpecMemoryAuditReport
    from echelon.cli import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        lambda project_root, selector, probe_retrieval=False: SpecMemoryAuditReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing=None,
            palace_path=None,
            status="unavailable",
            expected_count=0,
            present_current_count=0,
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["echelon", "spec", "memory", "audit", "003-demo", "--json"],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2


@pytest.mark.unit
def test_spec_memory_audit_json_does_not_require_legacy_config(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "mempalace:\n  wing: demo-wing\n",
        encoding="utf-8",
    )
    spec_dir = tmp_path / "specs" / "003-demo"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("spec.md").write_text("FR-001: Upload a photo.\n", encoding="utf-8")

    class EmptyCollection:
        def get(self, ids=None, where=None, include=None, limit=None):
            return {"ids": [], "documents": [], "metadatas": []}

    monkeypatch.setattr(
        "echelon.mempalace_requirements.RequirementMemoryAdapter.open_collection_read_only",
        lambda self: EmptyCollection(),
    )
    monkeypatch.chdir(tmp_path)
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "audit", "003-demo", "--json"])

    assert result.exit_code == 1
    assert '"status": "fail"' in result.output
    assert "SystemExit" not in result.output


@pytest.mark.unit
def test_spec_memory_refresh_runs_mine_then_audit(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_audit import SpecMemoryAuditReport
    from echelon.mempalace_requirements import SpecMemoryMineReport

    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_requirements.mine_spec_requirements",
        lambda project_root, selector, run_id: calls.append(("mine", selector)) or SpecMemoryMineReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="complete",
            expected_count=1,
            written_count=1,
            adopted_count=0,
            skipped_count=0,
            failed_count=0,
            drifted_count=0,
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        lambda project_root, selector, probe_retrieval=False: calls.append(("audit", selector)) or SpecMemoryAuditReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="pass",
            expected_count=1,
            present_current_count=1,
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "refresh", "003-demo"])

    assert result.exit_code == 0
    assert calls == [("mine", "003-demo"), ("audit", "003-demo")]


@pytest.mark.unit
def test_spec_memory_audit_invalid_selector_is_bounded(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "audit", "runs/x/specs/003-demo"])

    assert result.exit_code == 2
    assert "run-local specs are not supported" in result.output
    assert "Traceback" not in result.output


@pytest.mark.unit
def test_spec_memory_mine_invalid_selector_is_bounded(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "mine", "runs/x/specs/003-demo"])

    assert result.exit_code == 2
    assert "run-local specs are not supported" in result.output
    assert "Traceback" not in result.output


@pytest.mark.unit
def test_spec_memory_refresh_invalid_selector_is_bounded(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "refresh", "runs/x/specs/003-demo"])

    assert result.exit_code == 2
    assert "run-local specs are not supported" in result.output
    assert "Traceback" not in result.output


@pytest.mark.unit
def test_spec_memory_mine_does_not_write_unavailable_report(
    monkeypatch, tmp_path: Path
) -> None:
    from echelon.mempalace_requirements import SpecMemoryMineReport

    spec_dir = tmp_path / "specs" / "003-demo"
    spec_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_requirements.mine_spec_requirements",
        lambda project_root, selector, run_id: SpecMemoryMineReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(spec_dir),
            wing="demo-wing",
            palace_path=".mempalace",
            status="unavailable",
            expected_count=1,
            written_count=0,
            adopted_count=0,
            skipped_count=0,
            failed_count=0,
            drifted_count=0,
            unavailable_count=1,
        ),
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["spec", "memory", "mine", "003-demo", "--write-report"],
    )

    assert result.exit_code == 2
    assert not spec_dir.joinpath("mempalace-mine.json").exists()


@pytest.mark.unit
def test_spec_memory_refresh_no_audit_skips_audit(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_requirements import SpecMemoryMineReport

    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_requirements.mine_spec_requirements",
        lambda project_root, selector, run_id: SpecMemoryMineReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="complete",
            expected_count=1,
            written_count=0,
            adopted_count=1,
            skipped_count=0,
            failed_count=0,
            drifted_count=0,
        ),
    )
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        lambda *args, **kwargs: calls.append("audit"),
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["spec", "memory", "refresh", "003-demo", "--no-audit"],
    )

    assert result.exit_code == 0
    assert calls == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "expected_exit", "expected_writes"),
    (("pass", 0, 1), ("unavailable", 2, 0)),
)
def test_spec_memory_audit_write_respects_availability(
    monkeypatch,
    tmp_path: Path,
    status: str,
    expected_exit: int,
    expected_writes: int,
) -> None:
    from echelon.mempalace_audit import SpecMemoryAuditReport

    writes = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        lambda project_root, selector, probe_retrieval=False: SpecMemoryAuditReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing" if status == "pass" else None,
            palace_path=".mempalace" if status == "pass" else None,
            status=status,
            expected_count=1,
            present_current_count=1 if status == "pass" else 0,
        ),
    )
    monkeypatch.setattr(
        "echelon.mempalace_audit.write_audit_reports",
        lambda report, spec_dir: writes.append((report, spec_dir)),
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["spec", "memory", "audit", "003-demo", "--write"],
    )

    assert result.exit_code == expected_exit
    assert len(writes) == expected_writes
