from pathlib import Path

from harness.extension_drift import assess_extension_drift


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_assess_extension_drift_reports_in_sync_copy(tmp_path: Path) -> None:
    source = tmp_path / "source" / "extension"
    installed = tmp_path / "project" / ".specify" / "extensions" / "echelon"
    _write(source / "extension.yml", "name: echelon\n")
    _write(source / "agents" / "control" / "commander.md", "source\n")
    _write(installed / "extension.yml", "name: echelon\n")
    _write(installed / "agents" / "control" / "commander.md", "source\n")

    report = assess_extension_drift(source, installed)

    assert report.status == "in_sync"
    assert report.drifted is False
    assert report.changed_files == []


def test_assess_extension_drift_reports_changed_missing_and_extra_files(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source" / "extension"
    installed = tmp_path / "project" / ".specify" / "extensions" / "echelon"
    _write(source / "extension.yml", "name: echelon\n")
    _write(source / "agents" / "control" / "commander.md", "new\n")
    _write(source / "workflow" / "definition.yaml", "phases: []\n")
    _write(installed / "extension.yml", "name: echelon\n")
    _write(installed / "agents" / "control" / "commander.md", "old\n")
    _write(installed / "templates" / "stale.md", "extra\n")

    report = assess_extension_drift(source, installed)

    assert report.status == "drifted"
    assert report.drifted is True
    assert report.changed_files == ["agents/control/commander.md"]
    assert report.missing_files == ["workflow/definition.yaml"]
    assert report.extra_files == ["templates/stale.md"]


def test_assess_extension_drift_ignores_project_local_config(tmp_path: Path) -> None:
    source = tmp_path / "source" / "extension"
    installed = tmp_path / "project" / ".specify" / "extensions" / "echelon"
    _write(source / "extension.yml", "name: echelon\n")
    _write(source / "echelon-config.yml", "harness:\n  a: source\n")
    _write(installed / "extension.yml", "name: echelon\n")
    _write(installed / "echelon-config.yml", "harness:\n  a: project\n")
    _write(installed / "local-config.yml", "harness:\n  local: true\n")

    report = assess_extension_drift(source, installed)

    assert report.status == "in_sync"
    assert report.drifted is False
