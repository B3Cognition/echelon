from pathlib import Path

from scripts.ns003_experiment import find_calibration_set


def test_find_calibration_set_uses_canonical_specs_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calibration = tmp_path / "specs" / "015-calibration"
    calibration.mkdir(parents=True)
    (calibration / "spec.md").write_text("# Calibration\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    selected, source = find_calibration_set(None)

    assert selected == Path("specs/015-calibration")
    assert source == "runs_015_016"


def test_find_calibration_set_ignores_legacy_specs_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    legacy = tmp_path / ".specify" / "specs" / "015-legacy"
    legacy.mkdir(parents=True)
    (legacy / "spec.md").write_text("# Legacy\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert find_calibration_set(None) == (None, "not_found")
